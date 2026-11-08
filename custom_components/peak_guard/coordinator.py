"""Home Assistant coordinator for PeakPilot."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
import logging
from typing import Any

from homeassistant.components.recorder import history as recorder_history
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .peak_manager import PeakManager

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
        entry_id: str | None = None,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name="peakpilot",
            update_interval=timedelta(seconds=5),
        )

        self.config = config
        self.entry_id = entry_id
        self.store = Store(hass, self.STORAGE_VERSION, f"{self.STORAGE_KEY}_{entry_id}") if entry_id else None
        self.peak_manager = PeakManager()

        self.target_peak_kw = float(config.get("target_peak_kw", 3.5))
        self.max_discharge_w = float(config.get("max_discharge_w", 2500))
        self.min_soc = float(config.get("min_soc", 20.0))

        self.history_restore_attempted = False
        self.history_restore_success = False

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
            self.peak_manager = PeakManager.from_dict(saved)
        except Exception:
            _LOGGER.exception("PeakPilot could not restore runtime state")
            return False

        _LOGGER.info("PeakPilot restored runtime accounting state")
        return True

    async def async_save_runtime_state(self) -> None:
        """Persist the current accounting state for the next startup."""
        if self.store is None:
            return

        try:
            await self.store.async_save(self.peak_manager.to_dict())
        except Exception:
            _LOGGER.exception("PeakPilot could not save runtime state")

    def _calculate_discharge_setpoint(
        self,
        grid_power_w: float,
        battery_soc: float,
        status: dict[str, Any],
    ) -> float:
        """Calculate a positive battery discharge request in watts."""
        if battery_soc <= self.min_soc:
            return 0.0

        if not status["control_data_valid"]:
            return 0.0

        remaining_seconds = status["remaining_seconds"]
        imported_energy_kwh = status["imported_energy_kwh"]

        if remaining_seconds is None or remaining_seconds <= 0:
            return 0.0

        max_interval_energy_kwh = self.target_peak_kw * 0.25
        remaining_energy_kwh = (
            max_interval_energy_kwh - imported_energy_kwh
        )

        allowed_grid_power_w = (
            remaining_energy_kwh
            * 3_600_000.0
            / remaining_seconds
        )

        required_discharge_w = max(
            0.0,
            grid_power_w - allowed_grid_power_w,
        )

        return min(required_discharge_w, self.max_discharge_w)

    async def _async_update_data(self) -> dict[str, Any]:
        """Read current Home Assistant states and update the peak manager."""
        grid_entity = self.config["grid_sensor"]
        soc_entity = self.config["soc_sensor"]

        grid_state = self.hass.states.get(grid_entity)
        soc_state = self.hass.states.get(soc_entity)

        if grid_state is None or grid_state.state in (
            "unknown", "unavailable"
        ):
            return {"available": False, "reason": "grid_sensor_unavailable"}

        if soc_state is None or soc_state.state in (
            "unknown", "unavailable"
        ):
            return {"available": False, "reason": "soc_sensor_unavailable"}

        try:
            grid_power_w = float(grid_state.state)
            battery_soc = float(soc_state.state)
        except (TypeError, ValueError) as err:
            return {
                "available": False,
                "reason": f"invalid_sensor_value: {err}",
            }

        # Use the sensor's measurement timestamp, not the coordinator poll
        # time. This avoids pretending a stale sensor value is a fresh sample.
        sample_time = grid_state.last_updated
        if sample_time.tzinfo is None:
            sample_time = sample_time.replace(tzinfo=timezone.utc)

        self.peak_manager.update(grid_power_w, sample_time)
        await self.async_save_runtime_state()

        now = dt_util.now()
        status = self.peak_manager.get_status(now)

        setpoint_w = self._calculate_discharge_setpoint(
            grid_power_w,
            battery_soc,
            status,
        )

        return {
            "available": True,
            "grid_power_w": grid_power_w,
            "battery_soc": battery_soc,
            "battery_setpoint_w": setpoint_w,
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
