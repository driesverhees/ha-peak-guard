"""Quarter-hour grid-import accounting for PeakPilot.

Positive grid power means import; negative power means export.
All interval boundaries are UTC epoch quarter-hours (900 seconds).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class PeakManager:
    """Integrate grid import and track valid quarter-hour peaks."""

    INTERVAL_SECONDS = 900.0
    MAX_SAMPLE_GAP_SECONDS = 30.0
    COVERAGE_TOLERANCE_SECONDS = 1.0

    def __init__(
        self,
        max_sample_gap_seconds: float = MAX_SAMPLE_GAP_SECONDS,
    ) -> None:
        self.max_sample_gap_seconds = max_sample_gap_seconds

        self._interval_id: int | None = None
        self._interval_energy_kwh = 0.0
        self._interval_coverage_seconds = 0.0
        self._interval_valid = False

        self._last_timestamp: float | None = None
        self._last_power_w: float | None = None
        self._timezone = None

        # Keys are local calendar months in YYYY-MM format.
        self.monthly_peaks: dict[str, float] = {}
        self.last_completed_peak_kw: float | None = None
        self.completed_intervals = 0
        self.invalid_intervals = 0

    @staticmethod
    def _get_interval_id(timestamp: float) -> int:
        return int(timestamp // PeakManager.INTERVAL_SECONDS)

    @staticmethod
    def _positive_import_energy_kwh(
        p1_w: float,
        p2_w: float,
        duration_seconds: float,
    ) -> float:
        """Integrate max(power, 0) with linear interpolation.

        This correctly handles a linear crossing between import and export.
        """
        if duration_seconds <= 0:
            return 0.0

        if p1_w >= 0.0 and p2_w >= 0.0:
            average_import_w = (p1_w + p2_w) / 2.0
        elif p1_w <= 0.0 and p2_w <= 0.0:
            average_import_w = 0.0
        elif p1_w > 0.0:
            # Positive to negative crossing.
            average_import_w = p1_w**2 / (2.0 * (p1_w - p2_w))
        else:
            # Negative to positive crossing.
            average_import_w = p2_w**2 / (2.0 * (p2_w - p1_w))

        return average_import_w * duration_seconds / 3_600_000.0

    def _start_interval(self, interval_id: int, valid: bool) -> None:
        self._interval_id = interval_id
        self._interval_energy_kwh = 0.0
        self._interval_coverage_seconds = 0.0
        self._interval_valid = valid

    def _month_for_interval(self, interval_id: int) -> str:
        interval_start_utc = datetime.fromtimestamp(
            interval_id * self.INTERVAL_SECONDS,
            tz=timezone.utc,
        ).astimezone(self._timezone)
        return interval_start_utc.strftime("%Y-%m")

    def _finish_interval(self) -> None:
        """Finalize current interval; only complete valid intervals count."""
        if self._interval_id is None:
            return

        complete = (
            self._interval_valid
            and self._interval_coverage_seconds
            >= self.INTERVAL_SECONDS - self.COVERAGE_TOLERANCE_SECONDS
        )

        if complete:
            peak_kw = self._interval_energy_kwh / 0.25
            month = self._month_for_interval(self._interval_id)

            self.monthly_peaks[month] = max(
                self.monthly_peaks.get(month, 0.0),
                peak_kw,
            )
            self.last_completed_peak_kw = peak_kw
            self.completed_intervals += 1
        else:
            self.invalid_intervals += 1

    def _handle_gap(self, new_timestamp: float) -> None:
        """Invalidate every interval touched by an unmeasured time gap."""
        assert self._interval_id is not None

        new_interval_id = self._interval_id(new_timestamp)

        if new_interval_id == self._interval_id:
            self._interval_valid = False
            return

        old_interval_id = self._interval_id
        self._interval_valid = False
        self._finish_interval()

        # Intervals entirely skipped by the gap are also unknown.
        for _ in range(old_interval_id + 1, new_interval_id):
            self.invalid_intervals += 1

        new_interval_start = new_interval_id * self.INTERVAL_SECONDS
        starts_exactly_at_boundary = (
            abs(new_timestamp - new_interval_start)
            <= self.COVERAGE_TOLERANCE_SECONDS
        )
        self._start_interval(
            new_interval_id,
            valid=starts_exactly_at_boundary,
        )

    def update(self, grid_power_w: float, now: datetime) -> dict[str, Any]:
        """Add one timestamped grid-power sample and return current status."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be a timezone-aware datetime")

        try:
            power_w = float(grid_power_w)
        except (TypeError, ValueError) as err:
            raise ValueError("grid_power_w must be numeric") from err

        if not (-10_000_000.0 < power_w < 10_000_000.0):
            raise ValueError("grid_power_w is outside the accepted range")

        timestamp = now.timestamp()
        self._timezone = now.tzinfo
        current_interval_id = self._get_interval_id(timestamp)

        # First sample: only a sample at the exact boundary can establish
        # complete coverage from the beginning of the quarter-hour.
        if self._last_timestamp is None:
            interval_start = current_interval_id * self.INTERVAL_SECONDS
            starts_at_boundary = (
                abs(timestamp - interval_start)
                <= self.COVERAGE_TOLERANCE_SECONDS
            )
            self._start_interval(current_interval_id, starts_at_boundary)
            self._last_timestamp = timestamp
            self._last_power_w = power_w
            return self.get_status(now)

        assert self._last_power_w is not None
        elapsed = timestamp - self._last_timestamp

        # Duplicate or out-of-order samples must never add energy.
        if elapsed <= 0:
            return self.get_status(now)

        if elapsed > self.max_sample_gap_seconds:
            self._handle_gap(timestamp)
            self._last_timestamp = timestamp
            self._last_power_w = power_w
            return self.get_status(now)

        # Integrate the line between samples, splitting exactly at
        # quarter-hour boundaries.
        cursor = self._last_timestamp
        while cursor < timestamp:
            segment_id = self._get_interval_id(cursor)

            if self._interval_id != segment_id:
                self._finish_interval()
                self._start_interval(segment_id, valid=True)

            boundary = (segment_id + 1) * self.INTERVAL_SECONDS
            segment_end = min(timestamp, boundary)
            duration = segment_end - cursor

            fraction_start = (cursor - self._last_timestamp) / elapsed
            fraction_end = (segment_end - self._last_timestamp) / elapsed

            p1_w = self._last_power_w + (
                power_w - self._last_power_w
            ) * fraction_start
            p2_w = self._last_power_w + (
                power_w - self._last_power_w
            ) * fraction_end

            self._interval_energy_kwh += self._positive_import_energy_kwh(
                p1_w, p2_w, duration
            )
            self._interval_coverage_seconds += duration
            cursor = segment_end

        self._last_timestamp = timestamp
        self._last_power_w = power_w
        return self.get_status(now)

    def get_status(self, now: datetime) -> dict[str, Any]:
        """Return accounting status without assuming missing energy is zero."""
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be a timezone-aware datetime")

        self._timezone = now.tzinfo
        now_timestamp = now.timestamp()
        now_interval_id = self._get_interval_id(now_timestamp)

        # Do not mutate accounting state from get_status(). Only update()
        # may advance intervals, because it has an actual measurement with
        # which to integrate (or detect a gap). If wall-clock time has moved
        # into a later interval before a new sample arrives, report control
        # data as invalid rather than finalizing an interval prematurely.
        month = now.strftime("%Y-%m")

        if self._interval_id is None:
            return {
                "interval_valid": False,
                "control_data_valid": False,
                "imported_energy_kwh": None,
                "coverage_seconds": 0.0,
                "remaining_seconds": None,
                "monthly_peak_kw": self.monthly_peaks.get(month),
                "last_completed_peak_kw": self.last_completed_peak_kw,
                "completed_intervals": self.completed_intervals,
                "invalid_intervals": self.invalid_intervals,
            }

        interval_start = self._interval_id * self.INTERVAL_SECONDS
        same_interval_as_now = now_interval_id == self._interval_id
        elapsed = max(0.0, min(
            self.INTERVAL_SECONDS, now_timestamp - interval_start
        )) if same_interval_as_now else 0.0
        remaining = max(0.0, self.INTERVAL_SECONDS - elapsed)

        # Control may use the partial energy only if coverage reaches close
        # enough to the present. A stale sensor sample is not treated as live.
        coverage_matches_elapsed = (
            self._interval_coverage_seconds
            >= elapsed - self.max_sample_gap_seconds
            - self.COVERAGE_TOLERANCE_SECONDS
        )
        control_data_valid = (
            self._interval_valid
            and same_interval_as_now
            and coverage_matches_elapsed
        )

        average_so_far_kw = None
        if elapsed > 0:
            average_so_far_kw = (
                self._interval_energy_kwh * 3600.0 / elapsed
            )

        return {
            "interval_valid": self._interval_valid,
            "control_data_valid": control_data_valid,
            "imported_energy_kwh": self._interval_energy_kwh,
            "coverage_seconds": self._interval_coverage_seconds,
            "elapsed_seconds": elapsed,
            "remaining_seconds": remaining,
            "average_import_so_far_kw": average_so_far_kw,
            "monthly_peak_kw": self.monthly_peaks.get(month),
            "last_completed_peak_kw": self.last_completed_peak_kw,
            "completed_intervals": self.completed_intervals,
            "invalid_intervals": self.invalid_intervals,
        }
