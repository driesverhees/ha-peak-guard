from custom_components.peak_guard.coordinator import CapacityCoordinator
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .entity import PeakGuardEntity

class CapacitySensor(PeakGuardEntity, SensorEntity):

    def __init__(self, coordinator : CapacityCoordinator, key, name, unit):
        super().__init__(coordinator, coordinator.config_entry)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"capacity_optimizer_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_native_value = None

    @property
    def native_value(self):
        if not self.coordinator.data.get("available"):
            return None
        return self.coordinator.data.get(self._key)


class VirtualAnkerSensor(PeakGuardEntity, SensorEntity):
    """Read-only Anker-compatible status sensor on a separate virtual device."""

    def __init__(
        self,
        coordinator: CapacityCoordinator,
        key: str,
        name: str,
        *,
        options: list[str] | None = None,
    ) -> None:
        super().__init__(coordinator, coordinator.config_entry)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry_id}_virtual_anker_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry_id}_virtual_anker")},
            name="Anker SOLIX Solarbank Max AC",
            manufacturer="Anker",
            model="Solarbank Max AC",
        )
        if options is not None:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = options
        else:
            self._attr_native_unit_of_measurement = "W"
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        if not self.coordinator.data.get("available"):
            return None
        return self.coordinator.data.get(self._key)


class VirtualEVCCBatterySensor(PeakGuardEntity, SensorEntity):
    """Expose the measured battery telemetry expected by EVCC."""

    def __init__(
        self,
        coordinator: CapacityCoordinator,
        key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator, coordinator.config_entry)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry_id}_virtual_evcc_battery_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry_id}_virtual_evcc_battery")},
            name="Peak Guard EVCC Battery",
            manufacturer="Peak Guard",
            model="EVCC-compatible virtual battery",
        )
        if key == "battery_soc":
            self._attr_native_unit_of_measurement = "%"
            self._attr_device_class = SensorDeviceClass.BATTERY
        else:
            self._attr_native_unit_of_measurement = "W"
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        if not self.coordinator.data.get("available"):
            return None
        return self.coordinator.data.get(self._key)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator : CapacityCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        CapacitySensor(
            coordinator,
            "grid_power_w",
            "Grid Power",
            "W",
        ),
        CapacitySensor(
            coordinator,
            "battery_soc",
            "Battery SOC",
            "%",
        ),
        CapacitySensor(
            coordinator,
            "battery_power_w",
            "Measured Battery Power",
            "W",
        ),
        CapacitySensor(
            coordinator,
            "export_safe_max_discharge_w",
            "Export-safe Maximum Discharge",
            "W",
        ),
        CapacitySensor(
            coordinator,
            "battery_setpoint_w",
            "Battery Setpoint",
            "W",
        ),
        CapacitySensor(
            coordinator,
            "operating_mode",
            "Battery Operating Mode",
            None,
        ),
        CapacitySensor(
            coordinator,
            "operating_mode_reason",
            "Battery Operating Mode Reason",
            None,
        ),
        CapacitySensor(
            coordinator,
            "available_solar_surplus_w",
            "Available Solar Surplus",
            "W",
        ),
        CapacitySensor(
            coordinator,
            "available_peak_headroom_w",
            "Available Peak Charging Headroom",
            "W",
        ),
        CapacitySensor(
            coordinator,
            "monthly_peak_kw",
            "Monthly Peak",
            "kW",
        ),
        CapacitySensor(
            coordinator,
            "imported_energy_kwh",
            "Quarter-hour Imported Energy",
            "kWh",
        ),
        CapacitySensor(
            coordinator,
            "remaining_seconds",
            "Quarter-hour Remaining Time",
            "s",
        ),
        CapacitySensor(
            coordinator,
            "remaining_power_w",
            "Quarter-hour Remaining Power",
            "W",
        ),
        CapacitySensor(
            coordinator,
            "allowed_grid_power_w",
            "Allowed Remaining Grid Power",
            "W",
        ),
        CapacitySensor(
            coordinator,
            "predicted_peak_kw",
            "Uncontrolled Projected Quarter-hour Peak",
            "kW",
        ),
        CapacitySensor(
            coordinator,
            "pi_error_w",
            "PI Controller Error",
            "W",
        ),
        CapacitySensor(
            coordinator,
            "pi_integral_w",
            "PI Integral Contribution",
            "W",
        ),
        CapacitySensor(
            coordinator,
            "pi_raw_output_w",
            "PI Unconstrained Output",
            "W",
        ),
        CapacitySensor(
            coordinator,
            "controller_status",
            "Controller Status",
            None,
        ),
        VirtualAnkerSensor(
            coordinator,
            "virtual_anker_operating_mode",
            "Operating Mode",
            options=["self_consumption", "third_party_control"],
        ),
        VirtualAnkerSensor(
            coordinator,
            "virtual_anker_grid_flow",
            "Grid Power",
            options=["charge", "discharge"],
        ),
        VirtualAnkerSensor(
            coordinator,
            "virtual_anker_power_w",
            "Power",
        ),
        VirtualEVCCBatterySensor(
            coordinator,
            "battery_soc",
            "State of Charge",
        ),
        VirtualEVCCBatterySensor(
            coordinator,
            "battery_power_w",
            "Power",
        ),
    ])
