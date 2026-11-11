
class ControllerResult:
    SelfConsumptionActive: bool = False
    PeakShavingActive: bool = False
    ForceGridChargingActive: bool = False
    DischargeSetpointW: float = 0.0
    ChargeSetpointW: float = 0.0

class PeakShavingController:

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

    def calculate_charge_setpoint(self, allow_grid_charging: bool = False) -> float:
        # Do not charge if the quarter-hour has already ended
        if self.remaining_seconds <= 0:
            return 0.0
        # Maximum allowed energy for this quarter-hour
        max_energy_kwh = self.target_peak_kw * 0.25
        # Remaining energy budget
        remaining_energy = max(0.0, max_energy_kwh - self.imported_energy_kwh)
        # Maximum allowed average import power
        if allow_grid_charging:
            allowed_grid_power_w = min(remaining_energy * 3_600_000.0 / self.remaining_seconds, self.max_grid_charge_w)
            return min(max(0.0, allowed_grid_power_w - self.grid_power_w), self.max_charge_w)
        elif self.grid_power_w < 0:
            return min(-self.grid_power_w, self.max_charge_w)
        else:
            return 0.0
    
    def run(self) -> ControllerResult:
        result = ControllerResult()
        result.SelfConsumptionActive = False
        result.PeakShavingActive = False
        result.ForceGridChargingActive = False
        # Determine the operating mode based on the battery SOC and the switch SOC
        if self.battery_soc >= self.switch_soc:
            # Battery SOC is above the switch SOC. Disabling peak shaving and doing self consumption only
            result.SelfConsumptionActive = True
        else:
            # Battery SOC is below the switch SOC. Enabling peak shaving
            if self.battery_soc < self.grid_charging_soc:
                # Battery SOC is below the grid charging SOC. Enabling grid charging
                result.ForceGridChargingActive = True
            result.PeakShavingActive = True
        # Always calculate the discharge setpoint, even if peak shaving is not active
        result.DischargeSetpointW = self.calculate_discharge_setpoint()
        result.ChargeSetpointW = self.calculate_charge_setpoint(allow_grid_charging=result.ForceGridChargingActive)
        return result