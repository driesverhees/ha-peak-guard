from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)


class CapacitySensor(CoordinatorEntity, SensorEntity):

    def __init__(self, coordinator, key, name, unit):
        super().__init__(coordinator)
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
    coordinator = hass.data["capacity_optimizer"][entry.entry_id]

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
    ])
