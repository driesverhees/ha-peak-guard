
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class PeakGuardBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of a Peak Guard binary sensor."""

    def __init__(self, coordinator, key, name, icon):
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_icon = icon

    @property
    def is_on(self):
        """Return the binary sensor state."""
        if not self.coordinator.data.get("available"):
            return None
        value = self.coordinator.data.get(self._key)
        if value is None:
            return None
        return bool(value)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Peak Guard binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        PeakGuardBinarySensor(coordinator, "control_data_valid", "Control Data Valid", "mdi:check-circle"),
        PeakGuardBinarySensor(coordinator, "battery_setpoint_w", "Discharge Required", "mdi:battery-arrow-down")
    ])
