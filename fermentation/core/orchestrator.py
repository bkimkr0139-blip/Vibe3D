"""
Fermentation facility orchestrator — SimPy-based event loop.

Transfer Line Flow (from P&ID Page 1):
  SEED 이송:  70L FER. → 700L FER. → 7KL FER.
  FEED 이송:  70L FEED → 70L FER.
              500L FEED → 700L FER.
              4KL FEED → 7KL FER.
  수확:       7KL FER. → 7KL BROTH

Modes:
  SINGLE_7KL   — PoC: single 7 KL fermentor only
  SEED_TRAIN   — 70 L → 700 L → 7 KL inoculation chain
  FULL_FACILITY — all vessels including feed/broth tanks
"""

from enum import Enum

import simpy

from fermentation.physics.fermentor import Fermentor, VESSEL_CONFIGS
from fermentation.physics.feed_tank import FeedTank, FEED_TANK_CONFIGS
from fermentation.physics.broth_tank import BrothTank
from fermentation.physics.sensor import VirtualSensor
from fermentation.control.dosing import DosingController


class FermentationMode(str, Enum):
    SINGLE_7KL = "single_7kl"
    SEED_TRAIN = "seed_train"
    FULL_FACILITY = "full_facility"


# ---------------------------------------------------------------------------
# Transfer line connections (from P&ID Page 1: Transfer Line Flow)
# ---------------------------------------------------------------------------
SEED_TRAIN_ORDER = ["KF-70L", "KF-700L", "KF-7KL"]

FEED_TANK_MAP = {
    # fermentor → feed tank (from P&ID connections)
    "KF-70L":  "KF-70L-FD",
    "KF-700L": "KF-500L-FD",
    "KF-7KL":  "KF-4KL-FD",
}

BROTH_TANK_MAP = {
    # fermentor → broth tank
    "KF-7KL": "KF-7000L",
}


class FermentationOrchestrator:
    """Coordinates all fermentation equipment via SimPy."""

    def __init__(self,
                 mode: FermentationMode = FermentationMode.SINGLE_7KL,
                 dt: float = 1.0,
                 realtime_factor: float = 1.0):
        self.mode = mode
        self.dt = dt
        self.realtime_factor = realtime_factor
        self.env = simpy.Environment()
        self._running = False
        self._state: dict = {}

        # --- Instantiate equipment based on mode ---
        self.fermentors: dict[str, Fermentor] = {}
        self.feed_tanks: dict[str, FeedTank] = {}
        self.broth_tank: BrothTank | None = None
        self.sensors: dict[str, dict[str, VirtualSensor]] = {}
        self.dosing_controllers: dict[str, DosingController] = {}

        if mode == FermentationMode.SINGLE_7KL:
            self._setup_single_7kl()
        elif mode == FermentationMode.SEED_TRAIN:
            self._setup_seed_train()
        elif mode == FermentationMode.FULL_FACILITY:
            self._setup_full_facility()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------
    def _create_sensors(self, vessel_name: str) -> dict[str, VirtualSensor]:
        """Create standard sensor set for a fermentor (per P&ID instrument list)."""
        return {
            "pH": VirtualSensor("pH"),
            "DO": VirtualSensor("DO"),
            "temperature": VirtualSensor("temperature"),
            "pressure": VirtualSensor("pressure"),
        }

    def _create_dosing_controllers(self, vessel_name: str):
        """Create base and acid dosing controllers per vessel.

        Dosing flow rates are derived from pipe sizes in VESSEL_CONFIGS.
        """
        vc = VESSEL_CONFIGS.get(vessel_name, {})
        base_flow = vc.get("base_flow_L_h", 5.0)
        acid_flow = vc.get("acid_flow_L_h", 5.0)

        self.dosing_controllers[f"{vessel_name}-base"] = DosingController(
            name=f"{vessel_name}-base",
            dose_open_s=15.0,
            dose_pause_s=13.0,
            max_doses=3,
            flow_rate_L_per_h=base_flow,
        )
        self.dosing_controllers[f"{vessel_name}-acid"] = DosingController(
            name=f"{vessel_name}-acid",
            dose_open_s=10.0,
            dose_pause_s=10.0,
            max_doses=3,
            flow_rate_L_per_h=acid_flow,
        )

    def _setup_single_7kl(self):
        f = Fermentor({"vessel": "KF-7KL"})
        self.fermentors["KF-7KL"] = f
        self.sensors["KF-7KL"] = self._create_sensors("KF-7KL")
        self._create_dosing_controllers("KF-7KL")

    def _setup_seed_train(self):
        """Seed train: KF-70L → KF-700L → KF-7KL (from Transfer Line Flow)."""
        for vessel in SEED_TRAIN_ORDER:
            self.fermentors[vessel] = Fermentor({"vessel": vessel})
            self.sensors[vessel] = self._create_sensors(vessel)
            self._create_dosing_controllers(vessel)

    def _setup_full_facility(self):
        """Full facility: all fermentors + feed tanks + broth tank."""
        self._setup_seed_train()

        # Feed tanks (from P&ID Pages 5-7)
        for ft_name in FEED_TANK_CONFIGS:
            self.feed_tanks[ft_name] = FeedTank({"vessel": ft_name})

        # Broth tank (from P&ID Page 8)
        self.broth_tank = BrothTank()

    # ------------------------------------------------------------------
    # Simulation loop
    # ------------------------------------------------------------------
    def _simulation_loop(self, env: simpy.Environment):
        """Main SimPy process — step all equipment each tick."""
        while self._running:
            state = {
                "simulation_time": round(env.now, 3),
                "mode": self.mode.value,
                "fermentors": {},
                "feed_tanks": {},
                "broth_tank": None,
                "sensors": {},
                "dosing": {},
                "connections": {
                    "seed_train": SEED_TRAIN_ORDER,
                    "feed_map": FEED_TANK_MAP,
                    "broth_map": BROTH_TANK_MAP,
                },
            }

            # Step fermentors
            for name, ferm in self.fermentors.items():
                # Apply dosing controller outputs to fermentor valves
                base_ctrl = self.dosing_controllers.get(f"{name}-base")
                if base_ctrl and base_ctrl.is_active:
                    base_ctrl.step(self.dt)
                    ferm.step(self.dt, valve_base=base_ctrl.valve_open)
                else:
                    ferm.step(self.dt)

                ferm_state = ferm.get_state()
                state["fermentors"][name] = ferm_state

                # Read sensors
                if name in self.sensors:
                    sensor_readings = {}
                    for stype, sensor in self.sensors[name].items():
                        true_val = ferm_state.get(
                            stype,
                            ferm_state.get("temperature", 0.0)
                        )
                        sensor_readings[stype] = round(
                            sensor.read(true_val, self.dt), 4
                        )
                    state["sensors"][name] = sensor_readings

                # Dosing state
                for dc_name, dc in self.dosing_controllers.items():
                    if dc_name.startswith(name):
                        state["dosing"][dc_name] = dc.get_state()

            # Step feed tanks
            for name, ft in self.feed_tanks.items():
                ft.step(self.dt)
                state["feed_tanks"][name] = ft.get_state()

            # Step broth tank
            if self.broth_tank is not None:
                self.broth_tank.step(self.dt)
                state["broth_tank"] = self.broth_tank.get_state()

            self._state = state
            yield env.timeout(self.dt)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self):
        """Start the simulation loop."""
        self._running = True
        self.env.process(self._simulation_loop(self.env))

    def run(self, duration_s: float):
        """Run simulation for a given duration (non-realtime)."""
        if not self._running:
            self.start()
        self.env.run(until=self.env.now + duration_s)

    def stop(self):
        """Stop the simulation."""
        self._running = False

    def apply_control(self, vessel_name: str, controls: dict):
        """
        Apply control inputs to a vessel.

        controls: dict of parameter names matching Fermentor.step() kwargs
          e.g. {"rpm_setpoint": 200, "aeration_vvm": 0.5, "valve_base": True}
        """
        ferm = self.fermentors.get(vessel_name)
        if ferm is None:
            return

        # Handle dosing controller triggers
        if controls.get("start_base_dosing"):
            dc = self.dosing_controllers.get(f"{vessel_name}-base")
            if dc:
                dc.start()
            controls.pop("start_base_dosing", None)

        if controls.get("start_acid_dosing"):
            dc = self.dosing_controllers.get(f"{vessel_name}-acid")
            if dc:
                dc.start()
            controls.pop("start_acid_dosing", None)

        # Apply remaining controls directly to fermentor
        # These will be picked up on the next step() call
        for key, value in controls.items():
            if hasattr(ferm, key):
                setattr(ferm, key, value)

    @property
    def current_state(self) -> dict:
        """Get the latest simulation state."""
        return self._state

    def get_sensor(self, vessel_name: str, sensor_type: str) -> VirtualSensor | None:
        """Get a specific sensor for fault injection etc."""
        vessel_sensors = self.sensors.get(vessel_name)
        if vessel_sensors is None:
            return None
        return vessel_sensors.get(sensor_type)
