from custom_components.peak_guard.coordinator import CapacityCoordinator
from homeassistant.components.sensor import SensorEntity

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
            "battery_setpoint_w",
            "Battery Setpoint",
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
    ])
