"""Home Assistant coordinator for PeakPilot."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
import logging
from typing import Any

from .controller import PeakPIController
from homeassistant.components.recorder import history as recorder_history
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .peak_manager import PeakManager
from .const import (
    DEFAULT_PI_KP,
    DEFAULT_PI_KI,
    DEFAULT_ACTIVATION_THRESHOLD_W,
    DEFAULT_DEACTIVATION_THRESHOLD_W,
    DEFAULT_RAMP_RATE_W_PER_S,
    DEFAULT_MINIMUM_ON_TIME_S,
    DEFAULT_MINIMUM_OFF_TIME_S,
    DEFAULT_FILTER_TIME_S,
    DEFAULT_ANTI_WINDUP_TIME_S,
    DEFAULT_EXPORT_SAFETY_MARGIN_W,
)

_LOGGER = logging.getLogger(__name__)


class CapacityCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Collect grid/battery measurements and calculate a peak-shaving target.

    This coordinator is deliberately dry-run only: it calculates and exposes
    a battery discharge setpoint but does not write to the battery.
    """

    STORAGE_KEY = "peak_guard_runtime_state"
    STORAGE_VERSION = 1

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name="peakpilot",
            update_interval=timedelta(seconds=5),
        )

        self.config = config
        self.config_entry = config_entry
        self.entry_id = config_entry.entry_id
        self.store = Store(
            hass,
            self.STORAGE_VERSION,
            f"{self.STORAGE_KEY}_{self.entry_id}",
        )
        self.peak_manager = PeakManager()

        self.target_peak_kw = float(config.get("target_peak_kw", 3.5))
        self.max_discharge_w = float(config.get("max_discharge_w", 2500))
        self.min_soc = float(config.get("min_soc", 20.0))
        self.switch_soc_threshold = float(config.get("switch_soc_threshold", 20.0))

        self.controller_settings = {
            "pi_kp": float(config.get("pi_kp", DEFAULT_PI_KP)),
            "pi_ki": float(config.get("pi_ki", DEFAULT_PI_KI)),
            "activation_threshold_w": float(config.get(
                "activation_threshold_w", DEFAULT_ACTIVATION_THRESHOLD_W
            )),
            "deactivation_threshold_w": float(config.get(
                "deactivation_threshold_w", DEFAULT_DEACTIVATION_THRESHOLD_W
            )),
            "ramp_rate_w_per_s": float(config.get(
                "ramp_rate_w_per_s", DEFAULT_RAMP_RATE_W_PER_S
            )),
            "minimum_on_time_s": float(config.get(
                "minimum_on_time_s", DEFAULT_MINIMUM_ON_TIME_S
            )),
            "minimum_off_time_s": float(config.get(
                "minimum_off_time_s", DEFAULT_MINIMUM_OFF_TIME_S
            )),
            "filter_time_s": float(config.get(
                "filter_time_s", DEFAULT_FILTER_TIME_S
            )),
            "anti_windup_time_s": float(config.get(
                "anti_windup_time_s", DEFAULT_ANTI_WINDUP_TIME_S
            )),
            "export_safety_margin_w": float(config.get(
                "export_safety_margin_w", DEFAULT_EXPORT_SAFETY_MARGIN_W
            )),
        }
        self.battery_power_sensor = config.get("battery_power_sensor")
        self.battery_power_sign = config.get("battery_power_sign", "positive_discharge")
        self.controller = self._new_controller()

        self.history_restore_attempted = False
        self.history_restore_success = False

    def _new_controller(self) -> PeakPIController:
        """Create the PI controller from the current options."""
        return PeakPIController(
            kp=self.controller_settings["pi_kp"],
            ki=self.controller_settings["pi_ki"],
            activation_threshold_w=self.controller_settings["activation_threshold_w"],
            deactivation_threshold_w=self.controller_settings["deactivation_threshold_w"],
            ramp_rate_w_per_s=self.controller_settings["ramp_rate_w_per_s"],
            minimum_on_time_s=self.controller_settings["minimum_on_time_s"],
            minimum_off_time_s=self.controller_settings["minimum_off_time_s"],
            filter_time_s=self.controller_settings["filter_time_s"],
            anti_windup_time_s=self.controller_settings["anti_windup_time_s"],
            max_discharge_w=self.max_discharge_w,
            min_soc=self.min_soc,
        )

    async def async_set_controller_setting(self, key: str, value: float) -> None:
        """Persist a controller tuning value and update the live controller."""
        if key not in self.controller_settings:
            raise ValueError(f"Unknown controller setting: {key}")
        self.controller_settings[key] = float(value)
        previous_state = self.controller.to_dict()
        self.controller = self._new_controller()
        self.controller.restore_state(previous_state)
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={
                **self.config_entry.options,
                key: float(value),
            },
        )
        await self.async_request_refresh()

    async def async_set_target_peak_kw(self, target_peak_kw: float) -> None:
        """Persist a new target and refresh the calculated setpoint."""
        self.target_peak_kw = target_peak_kw
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={
                **self.config_entry.options,
                "target_peak_kw": target_peak_kw,
            },
        )
        await self.async_request_refresh()

    async def async_set_switch_soc_threshold(self, switch_soc_threshold: float) -> None:
        """Persist a new switch SOC threshold and refresh the calculated setpoint."""
        self.switch_soc_threshold = switch_soc_threshold
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={
                **self.config_entry.options,
                "switch_soc_threshold": switch_soc_threshold,
            },
        )
        await self.async_request_refresh()

    @staticmethod
    def _quarter_start(now: datetime) -> datetime:
        """Return the start of the current local quarter-hour."""
        return now.replace(
            minute=(now.minute // 15) * 15,
            second=0,
            microsecond=0,
        )

    async def async_restore_current_interval(self) -> bool:
        """Rebuild the current quarter-hour from Recorder history.

        Recorder's include_start_time_state option supplies the last known
        state at/before the requested start, followed by changes in the range.
        That first state is replayed as the value at the quarter-hour boundary.
        """
        self.history_restore_attempted = True

        entity_id = self.config["grid_sensor"]
        now_local = dt_util.now()
        quarter_start_local = self._quarter_start(now_local)

        quarter_start_utc = quarter_start_local.astimezone(timezone.utc)
        now_utc = now_local.astimezone(timezone.utc)

        query = partial(
            recorder_history.get_significant_states,
            self.hass,
            quarter_start_utc,
            now_utc,
            entity_ids=[entity_id],
            include_start_time_state=True,
            significant_changes_only=False,
            minimal_response=False,
            no_attributes=True,
        )

        try:
            history = await self.hass.async_add_executor_job(query)
        except Exception:
            _LOGGER.exception(
                "PeakPilot could not retrieve Recorder history for %s",
                entity_id,
            )
            return False

        states = history.get(entity_id, [])
        if not states:
            _LOGGER.warning(
                "PeakPilot found no Recorder history for %s. "
                "The current quarter-hour will be treated as incomplete.",
                entity_id,
            )
            return False

        first_state = states[0]
        first_timestamp = first_state.last_updated

        # The first returned state must be the value that was already in
        # effect at the quarter-hour boundary. If the first state is later,
        # the missing beginning cannot safely be reconstructed.
        if first_timestamp > quarter_start_utc:
            _LOGGER.warning(
                "PeakPilot has no state at/before %s for %s; "
                "current interval cannot be reconstructed",
                quarter_start_utc,
                entity_id,
            )
            return False

        replayed = 0

        for index, state in enumerate(states):
            try:
                power_w = float(state.state)
            except (TypeError, ValueError):
                _LOGGER.warning(
                    "Skipping invalid historical value %r for %s",
                    state.state,
                    entity_id,
                )
                # A bad value creates an unknown gap. Do not silently bridge it.
                self.peak_manager = PeakManager()
                return False

            sample_time = state.last_updated.astimezone(timezone.utc)

            if index == 0:
                # The pre-boundary state is the power held at the beginning
                # of the interval. Anchor it at the quarter-hour boundary.
                sample_time = quarter_start_utc

            if sample_time > now_utc:
                continue

            self.peak_manager.update(power_w, sample_time)
            replayed += 1

        if self.peak_manager._interval_id is not None:
            self.peak_manager._finish_interval()

        status = self.peak_manager.get_status(now_local)
        self.history_restore_success = bool(
            replayed > 0 and status["control_data_valid"]
        )

        _LOGGER.info(
            "PeakPilot restored %d historical samples for %s; "
            "current interval control data valid: %s",
            replayed,
            entity_id,
            self.history_restore_success,
        )

        return self.history_restore_success

    async def async_restore_runtime_state(self) -> bool:
        """Restore the in-memory running quarter-hour state from stored data."""
        if self.store is None:
            return False

        try:
            saved = await self.store.async_load()
        except Exception:
            _LOGGER.exception("PeakPilot could not load runtime state")
            return False

        if not saved:
            return False

        try:
            # Accept the original v1 snapshot (PeakManager fields at root)
            # as well as the extended snapshot containing controller state.
            if "peak_manager" in saved:
                self.peak_manager = PeakManager.from_dict(saved["peak_manager"])
                self.controller.restore_state(saved.get("controller"))
            else:
                self.peak_manager = PeakManager.from_dict(saved)
        except Exception:
            _LOGGER.exception("PeakPilot could not restore runtime state")
            return False

        _LOGGER.info("PeakPilot restored runtime accounting and controller state")
        return True

    async def async_save_runtime_state(self) -> None:
        """Persist the current accounting state for the next startup."""
        if self.store is None:
            return

        try:
            await self.store.async_save({
                "peak_manager": self.peak_manager.to_dict(),
                "controller": self.controller.to_dict(),
            })
        except Exception:
            _LOGGER.exception("PeakPilot could not save runtime state")

    def _calculate_remaining_power_w(
        self,
        status: dict[str, Any],
    ) -> float:
        """Return the allowed grid import power remaining in the current quarter."""
        if not status["control_data_valid"]:
            return 0.0

        remaining_seconds = status["remaining_seconds"]
        imported_energy_kwh = status["imported_energy_kwh"]

        if remaining_seconds is None or remaining_seconds <= 0:
            return 0.0

        max_interval_energy_kwh = self.target_peak_kw * 0.25
        remaining_energy_kwh = max(
            0.0,
            max_interval_energy_kwh - (imported_energy_kwh or 0.0),
        )

        return (
            remaining_energy_kwh * 3_600_000.0 / remaining_seconds
        )

    @staticmethod
    def _state_power_to_w(state: Any) -> float:
        """Convert a sensor power state in W or kW to watts."""
        value = float(state.state)
        unit = (state.attributes.get("unit_of_measurement") or "W").lower()
        if unit in ("kw", "kilowatt", "kilowatts"):
            value *= 1000.0
        elif unit not in ("w", "watt", "watts"):
            raise ValueError(f"Unsupported power unit: {unit}")
        return value

    async def _async_update_data(self) -> dict[str, Any]:
        """Read current Home Assistant states and update the peak manager."""
        grid_entity = self.config["grid_sensor"]
        soc_entity = self.config["soc_sensor"]
        grid_state = self.hass.states.get(grid_entity)
        soc_state = self.hass.states.get(soc_entity)
        battery_power_state = self.hass.states.get(self.battery_power_sensor) if self.battery_power_sensor else None

        if grid_state is None or grid_state.state in ("unknown", "unavailable"):
            return {"available": False, "reason": "grid_sensor_unavailable"}
        if soc_state is None or soc_state.state in ("unknown", "unavailable"):
            return {"available": False, "reason": "soc_sensor_unavailable"}
        if battery_power_state is None or battery_power_state.state in ("unknown", "unavailable"):
            self.controller.inhibit("battery_power_sensor_unavailable")
            return {"available": False, "reason": "battery_power_sensor_unavailable"}

        try:
            grid_power_w = self._state_power_to_w(grid_state)
            battery_soc = float(soc_state.state)
            battery_power_raw_w = self._state_power_to_w(battery_power_state)
        except (TypeError, ValueError) as err:
            self.controller.inhibit("invalid_battery_or_grid_power")
            return {"available": False, "reason": f"invalid_sensor_value: {err}"}

        # The controller convention is positive = battery discharge.
        battery_power_w = (
            battery_power_raw_w
            if self.battery_power_sign == "positive_discharge"
            else -battery_power_raw_w
        )
        export_margin_w = self.controller_settings["export_safety_margin_w"]
        # Net grid import plus current battery discharge estimates household
        # consumption. Limit the absolute discharge setpoint so it cannot
        # exceed that consumption minus the configured safety margin.
        export_safe_max_w = max(
            0.0, grid_power_w + battery_power_w - export_margin_w
        )

        # Use the sensor's measurement timestamp, not the coordinator poll
        # time. This avoids pretending a stale sensor value is a fresh sample.
        sample_time = grid_state.last_updated
        if sample_time.tzinfo is None:
            sample_time = sample_time.replace(tzinfo=timezone.utc)

        self.peak_manager.update(grid_power_w, sample_time)

        now = dt_util.now()
        status = self.peak_manager.get_status(now)

        remaining_power_w = self._calculate_remaining_power_w(status)

        if status["control_data_valid"] and remaining_power_w is not None:
            setpoint_w = self.controller.update(
                grid_power_w=grid_power_w,
                allowed_grid_power_w=remaining_power_w,
                battery_soc=battery_soc,
                now=now,
                max_discharge_w=min(self.max_discharge_w, export_safe_max_w),
            )
        else:
            setpoint_w = self.controller.inhibit()

        await self.async_save_runtime_state()

        predicted_peak_kw = None
        if status["imported_energy_kwh"] is not None and status["remaining_seconds"] is not None:
            projected_energy_kwh = (
                status["imported_energy_kwh"]
                + max(0.0, grid_power_w) * status["remaining_seconds"] / 3_600_000.0
            )
            predicted_peak_kw = projected_energy_kwh / 0.25

        return {
            "available": True,
            "grid_power_w": grid_power_w,
            "battery_soc": battery_soc,
            "battery_power_w": battery_power_w,
            "export_safe_max_discharge_w": export_safe_max_w,
            "export_safety_margin_w": export_margin_w,
            "battery_setpoint_w": setpoint_w,
            "remaining_power_w": remaining_power_w,
            "allowed_grid_power_w": remaining_power_w,
            "predicted_peak_kw": predicted_peak_kw,
            "pi_error_w": self.controller.error_w,
            "pi_integral_w": self.controller.integral_w,
            "pi_raw_output_w": self.controller.raw_output_w,
            "controller_active": self.controller.is_active,
            "controller_status": self.controller.status,
            "target_peak_kw": self.target_peak_kw,
            "imported_energy_kwh": status["imported_energy_kwh"],
            "coverage_seconds": status["coverage_seconds"],
            "remaining_seconds": status["remaining_seconds"],
            "current_interval_valid": status["interval_valid"],
            "control_data_valid": status["control_data_valid"],
            "average_import_so_far_kw": status[
                "average_import_so_far_kw"
            ],
            "monthly_peak_kw": status["monthly_peak_kw"],
            "last_completed_peak_kw": status[
                "last_completed_peak_kw"
            ],
            "completed_intervals": status["completed_intervals"],
            "invalid_intervals": status["invalid_intervals"],
            "history_restore_success": self.history_restore_success,
        }

    async def async_restore_monthly_peak(self) -> bool:
        """Rebuild the current month’s peak from recorder history."""
        entity_id = self.config["grid_sensor"]
        now_local = dt_util.now()
        month_start_local = now_local.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        month_start_utc = month_start_local.astimezone(timezone.utc)
        now_utc = now_local.astimezone(timezone.utc)

        query = partial(
            recorder_history.get_significant_states,
            self.hass,
            month_start_utc,
            now_utc,
            entity_ids=[entity_id],
            include_start_time_state=True,
            significant_changes_only=False,
            minimal_response=False,
            no_attributes=True,
        )

        try:
            history = await self.hass.async_add_executor_job(query)
        except Exception:
            _LOGGER.exception(
                "PeakPilot could not restore monthly peak history for %s",
                entity_id,
            )
            return False

        states = history.get(entity_id, [])
        if not states:
            return False

        for state in states:
            try:
                power_w = float(state.state)
            except (TypeError, ValueError):
                continue

            sample_time = state.last_updated.astimezone(timezone.utc)
            self.peak_manager.update(power_w, sample_time)

        if self.peak_manager._interval_id is not None:
            self.peak_manager._finish_interval()

        return True
