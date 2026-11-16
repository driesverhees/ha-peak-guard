"""Battery peak-shaving controllers.

PeakPIController is a stateful, dry-run-friendly controller. Positive battery
power means discharge. It is deliberately independent of Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ControllerResult:
    """Result structure retained for the legacy controller."""

    SelfConsumptionActive: bool = False
    PeakShavingActive: bool = False
    ForceGridChargingActive: bool = False
    DischargeSetpointW: float = 0.0
    ChargeSetpointW: float = 0.0


class PeakPIController:
    """PI controller using the remaining quarter-hour energy budget.

    The integral and active state are intentionally retained across
    quarter-hour boundaries. A boundary only changes the energy-budget
    reference; it does not reset the controller.
    """

    def __init__(
        self,
        *,
        kp: float = 0.5,
        ki: float = 0.01,
        activation_threshold_w: float = 300.0,
        deactivation_threshold_w: float = 100.0,
        ramp_rate_w_per_s: float = 200.0,
        minimum_on_time_s: float = 120.0,
        minimum_off_time_s: float = 120.0,
        filter_time_s: float = 5.0,
        anti_windup_time_s: float = 15.0,
        max_discharge_w: float = 2500.0,
        min_soc: float = 20.0,
    ) -> None:
        self.kp = max(0.0, float(kp))
        self.ki = max(0.0, float(ki))
        self.activation_threshold_w = max(0.0, float(activation_threshold_w))
        self.deactivation_threshold_w = max(0.0, float(deactivation_threshold_w))
        self.ramp_rate_w_per_s = max(0.0, float(ramp_rate_w_per_s))
        self.minimum_on_time_s = max(0.0, float(minimum_on_time_s))
        self.minimum_off_time_s = max(0.0, float(minimum_off_time_s))
        self.filter_time_s = max(0.0, float(filter_time_s))
        # Back-calculation tracking time constant. Smaller values unwind
        # the integrator faster when power/ramp limits constrain the output.
        self.anti_windup_time_s = max(1.0, float(anti_windup_time_s))
        self.max_discharge_w = max(0.0, float(max_discharge_w))
        self.min_soc = float(min_soc)

        # integral_w is the integral contribution to the output, in watts.
        self.integral_w = 0.0
        self.battery_power_w = 0.0
        self.filtered_grid_power_w: float | None = None
        self.last_update_ts: float | None = None
        self.last_switch_ts: float | None = None
        self.interval_id: int | None = None
        self.is_active = False
        self.error_w = 0.0
        self.raw_output_w = 0.0
        self.status = "idle"

    @staticmethod
    def _timestamp(now: datetime | float) -> float:
        return now.timestamp() if isinstance(now, datetime) else float(now)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def _handle_interval_change(self, interval_id: int, error_w: float) -> None:
        """Keep the current output continuous when the budget rolls over."""
        if self.interval_id is None:
            self.interval_id = interval_id
            return
        if interval_id == self.interval_id:
            return

        # Bumpless transfer is only needed while actively discharging.
        # When idle, keep the integrator at zero so an old interval cannot
        # preload a future activation.
        if self.is_active:
            self.integral_w = self.battery_power_w - self.kp * error_w
        else:
            self.integral_w = 0.0
        self.interval_id = interval_id

    def _filter_grid_power(self, grid_power_w: float, dt: float) -> float:
        if self.filtered_grid_power_w is None or self.filter_time_s <= 0:
            self.filtered_grid_power_w = grid_power_w
        else:
            alpha = dt / (self.filter_time_s + dt)
            self.filtered_grid_power_w += alpha * (
                grid_power_w - self.filtered_grid_power_w
            )
        return self.filtered_grid_power_w

    def _apply_ramp(self, desired_w: float, dt: float) -> float:
        if self.ramp_rate_w_per_s <= 0:
            return desired_w
        max_change = self.ramp_rate_w_per_s * dt
        return self._clamp(
            desired_w,
            self.battery_power_w - max_change,
            self.battery_power_w + max_change,
        )

    def update(
        self,
        *,
        grid_power_w: float,
        allowed_grid_power_w: float,
        battery_soc: float,
        now: datetime | float,
        max_discharge_w: float | None = None,
    ) -> float:
        """Calculate a smoothed discharge setpoint in watts."""
        now_ts = self._timestamp(now)
        if self.last_update_ts is None:
            dt = 5.0
        else:
            dt = self._clamp(now_ts - self.last_update_ts, 0.1, 10.0)
        self.last_update_ts = now_ts

        interval_id = int(now_ts // 900)
        filtered_grid = self._filter_grid_power(float(grid_power_w), dt)
        self.error_w = filtered_grid - float(allowed_grid_power_w)
        self._handle_interval_change(interval_id, self.error_w)

        power_limit = self.max_discharge_w
        if max_discharge_w is not None:
            power_limit = min(power_limit, max(0.0, float(max_discharge_w)))

        # SOC reserve is a hard discharge inhibit.
        if float(battery_soc) <= self.min_soc or power_limit <= 0:
            self.is_active = False
            self.battery_power_w = 0.0
            self.integral_w = min(0.0, self.integral_w)
            self.raw_output_w = 0.0
            self.status = "soc_limit" if float(battery_soc) <= self.min_soc else "power_limit"
            return 0.0

        # Do not wake the battery for small excursions. Once active, keep it
        # active until the PI demand has decayed and the minimum-on time passed.
        if not self.is_active:
            off_time_elapsed = (
                self.last_switch_ts is None
                or now_ts - self.last_switch_ts >= self.minimum_off_time_s
            )
            if self.error_w >= self.activation_threshold_w and off_time_elapsed:
                self.is_active = True
                self.last_switch_ts = now_ts
                # Start without a discontinuous integral kick.
                self.integral_w = max(
                    self.integral_w,
                    self.battery_power_w - self.kp * self.error_w,
                )
            else:
                self.battery_power_w = 0.0
                self.raw_output_w = 0.0
                self.status = "waiting_for_threshold"
                return 0.0

        # Unconstrained PI output (before power and ramp limits).
        raw_output = self.kp * self.error_w + self.integral_w
        self.raw_output_w = raw_output

        # Apply both actuator constraints. The ramp-limited setpoint is the
        # achievable command for this update and is used by back-calculation.
        desired = self._clamp(raw_output, 0.0, power_limit)
        new_power = self._apply_ramp(desired, dt)
        # Export prevention is a hard safety constraint. It deliberately
        # overrides the normal ramp-down limit if the safe ceiling falls.
        new_power = min(new_power, power_limit)

        # Back-calculation anti-windup:
        #   dI/dt = Ki * error + (u_limited - u_raw) / Tt
        # This corrects the integral for both power saturation and ramp
        # limiting, rather than only freezing integration at power limits.
        tracking_error = new_power - raw_output
        self.integral_w += (
            self.ki * self.error_w
            + tracking_error / self.anti_windup_time_s
        ) * dt

        on_time_elapsed = (
            self.last_switch_ts is None
            or now_ts - self.last_switch_ts >= self.minimum_on_time_s
        )
        # Deactivation only occurs once the PI demand has relaxed to nearly
        # zero. A negative error naturally unwinds the integral first.
        if (
            on_time_elapsed
            and self.error_w <= -self.deactivation_threshold_w
            and new_power <= 25.0
        ):
            self.is_active = False
            self.last_switch_ts = now_ts
            new_power = 0.0
            self.integral_w = 0.0

        self.battery_power_w = new_power
        self.status = "discharging" if self.is_active else "idle"
        return self.battery_power_w

    def inhibit(self, status: str = "control_data_invalid") -> float:
        """Return zero when measurements are invalid without resetting PI state."""
        self.status = status
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize controller state for Home Assistant restart recovery."""
        return {
            "integral_w": self.integral_w,
            "battery_power_w": self.battery_power_w,
            "filtered_grid_power_w": self.filtered_grid_power_w,
            "last_switch_ts": self.last_switch_ts,
            "interval_id": self.interval_id,
            "is_active": self.is_active,
        }

    def restore_state(self, data: dict[str, Any] | None) -> None:
        """Restore persistent state; timing is re-anchored on the next update."""
        if not data:
            return
        self.integral_w = float(data.get("integral_w", 0.0))
        self.battery_power_w = float(data.get("battery_power_w", 0.0))
        filtered = data.get("filtered_grid_power_w")
        self.filtered_grid_power_w = None if filtered is None else float(filtered)
        self.last_switch_ts = data.get("last_switch_ts")
        self.interval_id = data.get("interval_id")
        self.is_active = bool(data.get("is_active", False))
        self.last_update_ts = None


class PeakShavingController:
    """Legacy instantaneous controller retained for backwards compatibility."""

    def __init__(
        self,
        grid_power_w: float,
        imported_energy_kwh: float,
        remaining_seconds: float,
        target_peak_kw: float,
        max_discharge_w: float,
        max_charge_w: float,
        max_grid_charge_w: float,
        min_soc: float,
        switch_soc: float,
        grid_charging_soc: float,
        battery_soc: float,
    ) -> None:
        self.grid_power_w = grid_power_w
        self.imported_energy_kwh = imported_energy_kwh
        self.remaining_seconds = remaining_seconds
        self.target_peak_kw = target_peak_kw
        self.max_discharge_w = max_discharge_w
        self.max_charge_w = max_charge_w
        self.max_grid_charge_w = max_grid_charge_w
        self.min_soc = min_soc
        self.switch_soc = switch_soc
        self.grid_charging_soc = grid_charging_soc
        self.battery_soc = battery_soc

    def calculate_discharge_setpoint(self) -> float:
        if self.battery_soc <= self.min_soc or self.remaining_seconds <= 0:
            return 0.0
        max_energy_kwh = self.target_peak_kw * 0.25
        remaining_energy = max(0.0, max_energy_kwh - self.imported_energy_kwh)
        allowed_grid_power_w = remaining_energy * 3_600_000.0 / self.remaining_seconds
        required_power_w = max(0.0, self.grid_power_w - allowed_grid_power_w)
        return min(required_power_w, self.max_discharge_w)

    def calculate_charge_setpoint(self, allow_grid_charging: bool = False) -> float:
        if self.remaining_seconds <= 0:
            return 0.0
        max_energy_kwh = self.target_peak_kw * 0.25
        remaining_energy = max(0.0, max_energy_kwh - self.imported_energy_kwh)
        if allow_grid_charging:
            allowed_grid_power_w = min(
                remaining_energy * 3_600_000.0 / self.remaining_seconds,
                self.max_grid_charge_w,
            )
            return min(max(0.0, allowed_grid_power_w - self.grid_power_w), self.max_charge_w)
        if self.grid_power_w < 0:
            return min(-self.grid_power_w, self.max_charge_w)
        return 0.0

    def run(self) -> ControllerResult:
        result = ControllerResult()
        if self.battery_soc >= self.switch_soc:
            result.SelfConsumptionActive = True
        else:
            if self.battery_soc < self.grid_charging_soc:
                result.ForceGridChargingActive = True
            result.PeakShavingActive = True
        result.DischargeSetpointW = self.calculate_discharge_setpoint()
        result.ChargeSetpointW = self.calculate_charge_setpoint(
            allow_grid_charging=result.ForceGridChargingActive
        )
        return result
