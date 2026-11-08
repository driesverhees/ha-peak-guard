
class PeakShavingController:

    def calculate(
        self,
        grid_power_w: float,
        imported_energy_kwh: float,
        remaining_seconds: float,
        target_peak_kw: float,
        max_discharge_w: float,
        min_soc: float,
        battery_soc: float,
    ) -> float:

        # Do not discharge below reserve SOC
        if battery_soc <= min_soc:
            return 0.0

        if remaining_seconds <= 0:
            return 0.0

        # Maximum allowed energy for this quarter-hour
        max_energy_kwh = target_peak_kw * 0.25

        # Remaining energy budget
        remaining_energy = max(
            0.0,
            max_energy_kwh - imported_energy_kwh
        )

        # Maximum allowed average import power
        allowed_grid_power_w = (
            remaining_energy * 3600
            / remaining_seconds * 1000
        )

        # Required battery discharge
        required_power_w = max(
            0.0,
            grid_power_w - allowed_grid_power_w
        )

        return min(
            required_power_w,
            max_discharge_w
        )