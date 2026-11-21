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
from .const import CONF_EMAIL, CONF_PASSWORD, CONF_REFRESH_TOKEN, DOMAIN, POLL_SECONDS, ROOMS_SECONDS, SETTLE_SECONDS

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
            try:
                return await self._fetch()
            except OasisAuthError:
                if not await self.sign_in_again():
                    raise
                return await self._fetch()
        except OasisAuthError as e:
            raise ConfigEntryAuthFailed("Oasis sign-in expired: sign in again") from e
        except OasisError as e:
            raise UpdateFailed(str(e)) from e

    async def _fetch(self) -> Snapshot:
        lights = await self.api.lights()
        known = {n for r in self._rooms for n in r.nodes}
        if time.time() - self._rooms_at > ROOMS_SECONDS or not set(lights) <= known:
            self._rooms = await self.api.rooms()
            self._rooms_at = time.time()
        return Snapshot([r for r in self._rooms if any(n in lights for n in r.nodes)], lights)

    async def sign_in_again(self) -> bool:
        """An email account signs itself in again with its saved password. False when
        there's no password, or Oasis refuses it (then the person has to)."""
        data = self.config_entry.data
        if not data.get(CONF_PASSWORD):
            return False
        try:
            tokens = await OasisApi.password_sign_in(self.api.session, data[CONF_EMAIL], data[CONF_PASSWORD])
        except OasisAuthError as e:
            _LOGGER.warning("Oasis refused the saved password: %s", e)
            return False
        self.api.refresh_token = tokens["refresh_token"]
        self.api.forget_access()
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**data, CONF_REFRESH_TOKEN: tokens["refresh_token"]}
        )
        _LOGGER.info("Signed in to Oasis again with the saved password")
        return True

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
            try:
                await self.api.set(nodes, params)
            except OasisAuthError:
                if not await self.sign_in_again():
                    raise
                await self.api.set(nodes, params)
        except OasisAuthError as e:
            self.config_entry.async_start_reauth(self.hass)
            raise OasisError("Oasis sign-in expired: sign in again") from e
        until = time.time() + SETTLE_SECONDS
        for n in nodes:
            old_until, old = self._sent.get(n, (0, {}))
            self._sent[n] = (until, {**(old if old_until > time.time() else {}), **params})
        self.async_update_listeners()
