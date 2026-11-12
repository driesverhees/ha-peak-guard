"""Number entities for Peak Guard."""

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import PERCENTAGE, UnitOfElectricCurrent, UnitOfPower

from .const import DOMAIN
from .coordinator import CapacityCoordinator
from .entity import PeakGuardEntity

class TargetPeakNumber(PeakGuardEntity, NumberEntity):
    """Expose the target peak as a configurable number."""

    _attr_has_entity_name = True
    _attr_name = "Target Peak"
    _attr_native_min_value = 0.5
    _attr_native_max_value = 20
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = "kW"
    _attr_mode = NumberMode.BOX
    _attr_device_class = NumberDeviceClass.POWER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: CapacityCoordinator) -> None:
        super().__init__(coordinator, coordinator.config_entry)
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

class SwitchSocThresholdNumber(PeakGuardEntity, NumberEntity):
    """Expose the switch SOC threshold as a configurable number."""

    _attr_has_entity_name = True
    _attr_name = "Switch SOC threshold"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: CapacityCoordinator) -> None:
        super().__init__(coordinator, coordinator.config_entry)
        self._attr_unique_id = f"{coordinator.entry_id}_switch_soc_threshold"

    @property
    def native_value(self) -> float:
        return self.coordinator.switch_soc_threshold

    async def async_set_native_value(self, value: float) -> None:
        if not self._attr_native_min_value <= value <= self._attr_native_max_value:
            raise ValueError(
                f"Switch SOC must be between {self._attr_native_min_value} "
                f"and {self._attr_native_max_value} %"
            )
        await self.coordinator.async_set_switch_soc_threshold(value)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator : CapacityCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TargetPeakNumber(coordinator)])
    async_add_entities([SwitchSocThresholdNumber(coordinator)])
