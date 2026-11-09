
class PeakShavingController:

    def __init__(
            self,
            grid_power_w: float,
            imported_energy_kwh: float,
            remaining_seconds: float,
            target_peak_kw: float,
            max_discharge_w: float,
            min_soc: float,
            battery_soc: float, 
            ) -> None:
        self.grid_power_w = grid_power_w
        self.imported_energy_kwh = imported_energy_kwh
        self.remaining_seconds = remaining_seconds
        self.target_peak_kw = target_peak_kw
        self.max_discharge_w = max_discharge_w
        self.min_soc = min_soc
        self.battery_soc = battery_soc

    def calculate_discharge_setpoint(self) -> float:
        # Do not discharge below reserve SOC
        if self.battery_soc <= self.min_soc:
            return 0.0
        # Do not discharge if the quarter-hour has already ended
        if self.remaining_seconds <= 0:
            return 0.0

        # Maximum allowed energy for this quarter-hour
        max_energy_kwh = self.target_peak_kw * 0.25

        # Remaining energy budget
        remaining_energy = max(0.0, max_energy_kwh - self.imported_energy_kwh)

        # Maximum allowed average import power
        allowed_grid_power_w = remaining_energy * 3_600_000.0 / self.remaining_seconds

        # Required battery discharge
        required_power_w = max(0.0, self.grid_power_w - allowed_grid_power_w)

        return min(required_power_w, self.max_discharge_w)