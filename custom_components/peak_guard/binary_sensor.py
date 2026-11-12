
from custom_components.peak_guard.coordinator import CapacityCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN
from .entity import PeakGuardEntity

class PeakGuardBinarySensor(PeakGuardEntity, BinarySensorEntity):
    """Representation of a Peak Guard binary sensor."""

    def __init__(self, coordinator : CapacityCoordinator, key, name, icon):
        super().__init__(coordinator, coordinator.config_entry)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.entry_id}_{key}"
        self._attr_icon = icon
        self.entity_description = BinarySensorEntityDescription(
            key=key,
            name=name,
            device_class=None)


    @property
    def is_on(self):
        """Return the binary sensor state."""
        if not self.coordinator.data.get("available"):
            return None
        value = self.coordinator.data.get(self._key)
        if value is None:
            return None
        return bool(value)


async def async_setup_entry(hass : HomeAssistant, entry : ConfigEntry, async_add_entities):
    coordinator : CapacityCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        PeakGuardBinarySensor(coordinator, "control_data_valid", "Control Data Valid", "mdi:check-circle"), #"Flag indicating whether the data used by the control algorithm is sufficiently reliable to make control decisions", 
        PeakGuardBinarySensor(coordinator, "battery_setpoint_w", "Discharge Required", "mdi:battery-arrow-down")
    ])
