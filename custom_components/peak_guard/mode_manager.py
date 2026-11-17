"""Operating-mode selection for bidirectional battery peak control."""

from __future__ import annotations

from typing import Any


class BatteryModeManager:
    """Select discharge, solar charging, grid charging, or idle.

    Grid charging is inhibited for the remainder of a quarter-hour after a
    discharge request has occurred. Solar tracking and discharge remain
    available at any time. Positive power means discharge; negative means
    charge.
    """

    def __init__(self) -> None:
        self.interval_id: int | None = None
        self.discharge_started_this_block = False
        self.mode = "idle"
        self.reason = "waiting_for_control_data"
        self.last_charge_setpoint_w = 0.0

    def _update_interval(self, interval_id: int) -> None:
        if self.interval_id != interval_id:
            self.interval_id = interval_id
            self.discharge_started_this_block = False

    def select_mode(
        self,
        *,
        interval_id: int,
        discharge_required: bool,
        discharge_active: bool,
        battery_soc: float,
        grid_charge_soc_limit: float,
        max_charge_soc: float,
        solar_surplus_w: float,
        available_peak_headroom_w: float,
        minimum_solar_surplus_w: float = 200.0,
        minimum_grid_charge_headroom_w: float = 500.0,
    ) -> tuple[str, str]:
        """Select a mode and return (mode, reason)."""
        self._update_interval(interval_id)

        if discharge_required:
            if discharge_active:
                self.discharge_started_this_block = True
                self.mode = "discharge"
                self.reason = "peak_protection"
            else:
                self.mode = "idle"
                self.reason = "peak_protection_waiting_or_unavailable"
            return self.mode, self.reason

        # Solar tracking is always allowed (subject to the battery's normal
        # upper SOC limit), including after a discharge in this block.
        if (
            battery_soc < max_charge_soc
            and solar_surplus_w >= minimum_solar_surplus_w
        ):
            self.mode = "solar_charge"
            self.reason = "solar_surplus"
            return self.mode, self.reason

        # Grid charging is the only mode blocked after a discharge request.
        if self.discharge_started_this_block:
            self.mode = "idle"
            self.reason = "grid_charging_blocked_after_discharge"
        elif battery_soc >= grid_charge_soc_limit:
            self.mode = "idle"
            self.reason = "grid_charge_soc_limit"
        elif available_peak_headroom_w < minimum_grid_charge_headroom_w:
            self.mode = "idle"
            self.reason = "insufficient_peak_headroom"
        else:
            self.mode = "grid_charge"
            self.reason = "available_peak_headroom"

        return self.mode, self.reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "interval_id": self.interval_id,
            "discharge_started_this_block": self.discharge_started_this_block,
            "mode": self.mode,
            "reason": self.reason,
            "last_charge_setpoint_w": self.last_charge_setpoint_w,
        }

    def restore_state(self, data: dict[str, Any] | None) -> None:
        if not data:
            return
        self.interval_id = data.get("interval_id")
        self.discharge_started_this_block = bool(
            data.get("discharge_started_this_block", False)
        )
        self.mode = str(data.get("mode", "idle"))
        self.reason = str(data.get("reason", "restored"))
        self.last_charge_setpoint_w = float(
            data.get("last_charge_setpoint_w", 0.0)
        )
