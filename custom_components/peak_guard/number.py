"""Number entities for Peak Guard."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CapacityCoordinator


class TargetPeakNumber(CoordinatorEntity[CapacityCoordinator], NumberEntity):
    """Expose the target peak as a configurable number."""

    _attr_has_entity_name = True
    _attr_name = "Target Peak"
    _attr_native_min_value = 0.5
    _attr_native_max_value = 20
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = "kW"
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: CapacityCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_target_peak_kw"

    @property
    def native_value(self) -> float:
        return self.coordinator.target_peak_kw

    async def async_set_native_value(self, value: float) -> None:
        if not self._attr_native_min_value <= value <= self._attr_native_max_value:
            raise ValueError(
                f"Target peak must be between {self._attr_native_min_value} "
                f"and {self._attr_native_max_value} kW"
            )

        await self.coordinator.async_set_target_peak_kw(value)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TargetPeakNumber(coordinator)])
