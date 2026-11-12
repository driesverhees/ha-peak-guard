"""Common entities for Peak Guard."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN


class PeakGuardEntity(CoordinatorEntity):

    _attr_has_entity_name = True

    def __init__(self, coordinator : CoordinatorEntity, config_entry: ConfigEntry):
        super().__init__(coordinator)
        if config_entry is None: 
            raise ValueError("config_entry cannot be None")
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, config_entry.entry_id)
            },
            name="Peak Guard",
            manufacturer="Peak Guard",
            model="Peak Guard",
            entry_type=DeviceEntryType.SERVICE,
        )