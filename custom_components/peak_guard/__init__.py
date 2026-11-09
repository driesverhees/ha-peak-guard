from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import CapacityCoordinator

from .const import DOMAIN

PLATFORMS = ["sensor", "number"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
):
    coordinator = CapacityCoordinator(
        hass,
        {**entry.data, **entry.options},
        entry,
    )

    if not await coordinator.async_restore_runtime_state():
        await coordinator.async_restore_current_interval()

    # Rebuild the current month from Recorder history at startup. This ensures
    # the monthly peak is restored even if the runtime snapshot is missing,
    # incomplete, or the current quarter-hour has not yet exceeded the
    # historical peak from earlier in the month.
    await coordinator.async_restore_monthly_peak()

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(
        DOMAIN, {}
    )[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(
        entry, PLATFORMS
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
):
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )

    if unload_ok:
        hass.data[DOMAIN].pop(
            entry.entry_id
        )

    return unload_ok