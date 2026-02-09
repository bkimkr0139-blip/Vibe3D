"""
Dosing controller — acid / base / antifoam injection.

PoC specification:
  - Base valve opens for 15 seconds per dose
  - Tank valve (feed line) opens for 13 seconds per cycle
  - 3 doses to recover pH from anomaly condition
"""


class DosingController:
    """
    Timed dosing controller for acid/base/antifoam.

    A dose = valve open for `dose_open_s` seconds,
    then closed for `dose_pause_s` seconds before the next dose.
    """

    def __init__(self,
                 name: str = "base_dosing",
                 dose_open_s: float = 15.0,
                 dose_pause_s: float = 13.0,
                 max_doses: int = 3,
                 flow_rate_L_per_h: float = 5.0):
        self.name = name
        self.dose_open_s = dose_open_s
        self.dose_pause_s = dose_pause_s
        self.max_doses = max_doses
        self.flow_rate = flow_rate_L_per_h  # L/h when valve is open

        # State
        self._active = False
        self._dose_count = 0
        self._phase = "idle"       # "idle", "dosing", "pause", "complete"
        self._phase_elapsed_s = 0.0
        self._valve_open = False
        self._total_dosed_L = 0.0

    @property
    def valve_open(self) -> bool:
        return self._valve_open

    @property
    def dose_count(self) -> int:
        return self._dose_count

    @property
    def is_complete(self) -> bool:
        return self._phase == "complete"

    @property
    def is_active(self) -> bool:
        return self._active

    def start(self):
        """Start dosing sequence."""
        if self._phase in ("idle", "complete"):
            self._active = True
            self._dose_count = 0
            self._phase = "dosing"
            self._phase_elapsed_s = 0.0
            self._valve_open = True

    def stop(self):
        """Abort dosing."""
        self._active = False
        self._phase = "idle"
        self._valve_open = False
        self._phase_elapsed_s = 0.0

    def reset(self):
        """Reset for a new dosing sequence."""
        self._active = False
        self._dose_count = 0
        self._phase = "idle"
        self._phase_elapsed_s = 0.0
        self._valve_open = False
        self._total_dosed_L = 0.0

    def step(self, dt: float) -> bool:
        """
        Advance dosing state machine by dt seconds.
        Returns True if valve is open (dosing active).
        """
        if not self._active:
            self._valve_open = False
            return False

        self._phase_elapsed_s += dt

        if self._phase == "dosing":
            self._valve_open = True
            # Accumulate dosed volume
            self._total_dosed_L += self.flow_rate * (dt / 3600.0)

            if self._phase_elapsed_s >= self.dose_open_s:
                self._dose_count += 1
                self._valve_open = False

                if self._dose_count >= self.max_doses:
                    self._phase = "complete"
                    self._active = False
                else:
                    self._phase = "pause"
                    self._phase_elapsed_s = 0.0

        elif self._phase == "pause":
            self._valve_open = False
            if self._phase_elapsed_s >= self.dose_pause_s:
                self._phase = "dosing"
                self._phase_elapsed_s = 0.0

        return self._valve_open

    def get_state(self) -> dict:
        return {
            "name": self.name,
            "active": self._active,
            "phase": self._phase,
            "dose_count": self._dose_count,
            "max_doses": self.max_doses,
            "valve_open": self._valve_open,
            "phase_elapsed_s": round(self._phase_elapsed_s, 2),
            "total_dosed_L": round(self._total_dosed_L, 4),
        }
