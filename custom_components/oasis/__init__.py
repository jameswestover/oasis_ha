"""Mixtiles Oasis lights, through Oasis's cloud."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OasisApi
from .const import CONF_REFRESH_TOKEN
from .coordinator import OasisConfigEntry, OasisCoordinator

PLATFORMS = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: OasisConfigEntry) -> bool:
    api = OasisApi(async_get_clientsession(hass), entry.data[CONF_REFRESH_TOKEN])
    coordinator = OasisCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OasisConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
