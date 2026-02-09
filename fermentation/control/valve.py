"""
Valve models for fermentation facility.

DiscreteValve  — pneumatic diaphragm on/off valve with open/close time
ControlValve   — proportional control valve (0-100%) with travel time
"""

import math


class DiscreteValve:
    """
    On/off pneumatic diaphragm valve.

    Models opening/closing transition time:
      - Command open → ramps from 0% to 100% over `open_time_s`
      - Command close → ramps from 100% to 0% over `close_time_s`
    """

    def __init__(self, name: str = "DV",
                 open_time_s: float = 1.5,
                 close_time_s: float = 1.0,
                 fail_position: str = "closed"):
        self.name = name
        self.open_time_s = max(0.01, open_time_s)
        self.close_time_s = max(0.01, close_time_s)
        self.fail_position = fail_position   # "closed" or "open"

        self._commanded = False
        self._position = 0.0  # 0.0 = fully closed, 1.0 = fully open

    @property
    def commanded(self) -> bool:
        return self._commanded

    @property
    def position(self) -> float:
        """Current valve position (0.0 to 1.0)."""
        return self._position

    @property
    def is_open(self) -> bool:
        return self._position >= 0.99

    @property
    def is_closed(self) -> bool:
        return self._position <= 0.01

    def open(self):
        self._commanded = True

    def close(self):
        self._commanded = False

    def step(self, dt: float):
        """Advance valve position by dt seconds."""
        if self._commanded:
            rate = 1.0 / self.open_time_s
            self._position = min(1.0, self._position + rate * dt)
        else:
            rate = 1.0 / self.close_time_s
            self._position = max(0.0, self._position - rate * dt)

    def get_state(self) -> dict:
        return {
            "name": self.name,
            "commanded": self._commanded,
            "position": round(self._position, 4),
            "is_open": self.is_open,
            "is_closed": self.is_closed,
        }


class ControlValve:
    """
    Proportional control valve (0-100%).

    Models travel time: valve position ramps to setpoint at a fixed rate.
    """

    def __init__(self, name: str = "CV",
                 travel_time_s: float = 5.0,
                 fail_position: float = 0.0):
        self.name = name
        self.travel_time_s = max(0.01, travel_time_s)
        self.fail_position = fail_position  # 0.0 to 100.0

        self._setpoint = 0.0    # 0-100 %
        self._position = 0.0    # 0-100 %

    @property
    def setpoint(self) -> float:
        return self._setpoint

    @property
    def position(self) -> float:
        return self._position

    def set(self, value: float):
        """Set valve opening (0-100%)."""
        self._setpoint = max(0.0, min(100.0, value))

    def step(self, dt: float):
        """Advance valve position toward setpoint."""
        # Full stroke in travel_time_s → rate = 100% / travel_time_s
        rate = 100.0 / self.travel_time_s
        diff = self._setpoint - self._position
        max_change = rate * dt
        if abs(diff) <= max_change:
            self._position = self._setpoint
        else:
            self._position += math.copysign(max_change, diff)

    def get_state(self) -> dict:
        return {
            "name": self.name,
            "setpoint": round(self._setpoint, 2),
            "position": round(self._position, 2),
        }
