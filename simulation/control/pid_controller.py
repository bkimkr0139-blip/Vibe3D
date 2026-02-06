"""PID controller for plant process control loops.

Used for:
    - Digester temperature control
    - Engine load/speed control
    - Boiler steam pressure control
    - Feedstock feed rate control
"""


class PIDController:
    """Discrete PID controller with anti-windup."""

    def __init__(
        self,
        kp: float = 1.0,
        ki: float = 0.1,
        kd: float = 0.0,
        setpoint: float = 0.0,
        output_min: float = 0.0,
        output_max: float = 100.0,
    ):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.output_min = output_min
        self.output_max = output_max

        self._integral = 0.0
        self._prev_error = 0.0

    def update(self, measured_value: float, dt: float) -> float:
        """Compute PID output.

        Args:
            measured_value: Current process variable.
            dt: Time step in seconds.

        Returns:
            Controller output (clamped to output_min..output_max).
        """
        error = self.setpoint - measured_value

        # Proportional
        p_term = self.kp * error

        # Integral with anti-windup
        self._integral += error * dt
        i_term = self.ki * self._integral

        # Derivative
        d_term = 0.0
        if dt > 0:
            d_term = self.kd * (error - self._prev_error) / dt
        self._prev_error = error

        output = p_term + i_term + d_term

        # Clamp and anti-windup
        if output > self.output_max:
            output = self.output_max
            self._integral -= error * dt  # back-calculate
        elif output < self.output_min:
            output = self.output_min
            self._integral -= error * dt

        return output

    def reset(self):
        """Reset controller state."""
        self._integral = 0.0
        self._prev_error = 0.0
