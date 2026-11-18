"""Select entities for Peak Guard."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import CapacityCoordinator
from .entity import PeakGuardEntity


class EVCCBatteryModeSelect(PeakGuardEntity, SelectEntity):
    """Expose EVCC's normal and hold-discharge battery modes."""

    _attr_options = ["normal", "hold"]

    def __init__(self, coordinator: CapacityCoordinator) -> None:
        super().__init__(coordinator, coordinator.config_entry)
        self._attr_name = "EVCC Battery Mode"
        self._attr_unique_id = f"{coordinator.entry_id}_evcc_battery_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry_id}_virtual_evcc_battery")},
            name="Peak Guard EVCC Battery",
            manufacturer="Peak Guard",
            model="EVCC-compatible virtual battery",
        )

    @property
    def current_option(self) -> str:
        return self.coordinator.evcc_battery_mode

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            raise ValueError(f"Unknown EVCC battery mode: {option}")
        await self.coordinator.async_set_evcc_battery_mode(option)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CapacityCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EVCCBatteryModeSelect(coordinator)])
