"""Polls Oasis's cloud and holds what was sent until the lights report it."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OasisApi, OasisAuthError, OasisError, Snapshot
from .const import DOMAIN, POLL_SECONDS, ROOMS_SECONDS, SETTLE_SECONDS

_LOGGER = logging.getLogger(__name__)

type OasisConfigEntry = ConfigEntry[OasisCoordinator]


class OasisCoordinator(DataUpdateCoordinator[Snapshot]):
    config_entry: OasisConfigEntry

    def __init__(self, hass: HomeAssistant, entry: OasisConfigEntry, api: OasisApi) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=timedelta(seconds=POLL_SECONDS)
        )
        self.api = api
        self._rooms_at = 0.0
        self._rooms = []
        # light id -> (until, {"Power", "Brightness", "CCT"}) sent but not reported yet
        self._sent: dict[str, tuple[float, dict[str, Any]]] = {}

    async def _async_update_data(self) -> Snapshot:
        try:
            lights = await self.api.lights()
            known = {n for r in self._rooms for n in r.nodes}
            if time.time() - self._rooms_at > ROOMS_SECONDS or not set(lights) <= known:
                self._rooms = await self.api.rooms()
                self._rooms_at = time.time()
        except OasisAuthError as e:
            raise ConfigEntryAuthFailed("Oasis sign-in expired: sign in again") from e
        except OasisError as e:
            raise UpdateFailed(str(e)) from e
        return Snapshot([r for r in self._rooms if any(n in lights for n in r.nodes)], lights)

    def reported(self, node: str) -> dict[str, Any]:
        """A light as reported, with anything sent that it hasn't reported yet."""
        light = self.data.lights[node]
        now = {"Power": light.power, "Brightness": light.brightness, "CCT": light.kelvin}
        until, sent = self._sent.get(node, (0, {}))
        if until < time.time() or all(now.get(k) == v for k, v in sent.items()):
            self._sent.pop(node, None)
            return now
        return {**now, **sent}

    async def send(self, nodes: list[str], params: dict[str, Any]) -> None:
        try:
            await self.api.set(nodes, params)
        except OasisAuthError as e:
            self.config_entry.async_start_reauth(self.hass)
            raise OasisError("Oasis sign-in expired: sign in again") from e
        until = time.time() + SETTLE_SECONDS
        for n in nodes:
            old_until, old = self._sent.get(n, (0, {}))
            self._sent[n] = (until, {**(old if old_until > time.time() else {}), **params})
        self.async_update_listeners()
