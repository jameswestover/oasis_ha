"""One light per Oasis room (all its lights together), and one per light that's in no room."""

from __future__ import annotations

import collections
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import OasisError
from .const import DOMAIN, MAX_KELVIN, MIN_KELVIN, TONES
from .coordinator import OasisConfigEntry, OasisCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: OasisConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    added: set[str] = set()

    @callback
    def add_new() -> None:
        new = [r for r in coordinator.data.rooms if r.id not in added]
        added.update(r.id for r in new)
        if new:
            async_add_entities(OasisLight(coordinator, r.id) for r in new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


def to_ha(level: int) -> int:
    return round(max(0, min(100, level)) * 255 / 100)


def to_oasis(brightness: int) -> int:
    return max(1, min(100, round(brightness * 100 / 255)))


class OasisLight(CoordinatorEntity[OasisCoordinator], LightEntity):
    _attr_has_entity_name = True
    _attr_name = None  # the device's name
    _attr_color_mode = ColorMode.COLOR_TEMP
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = list(TONES)
    _attr_min_color_temp_kelvin = MIN_KELVIN
    _attr_max_color_temp_kelvin = MAX_KELVIN

    def __init__(self, coordinator: OasisCoordinator, room_id: str) -> None:
        super().__init__(coordinator)
        self.room_id = room_id
        self._attr_unique_id = room_id
        room = self._room()
        name = room.name and "Oasis lights"
        if not name:
            light = coordinator.data.lights.get(room.nodes[0])
            name = light.name if light else "Oasis light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room_id)},
            name=name,
            manufacturer="Mixtiles",
            model=f"Oasis ({len(room.nodes)} lights)" if room.name else "Oasis",
            suggested_area=room.name or None,
        )

    def _room(self):
        return next((r for r in self.coordinator.data.rooms if r.id == self.room_id), None)

    def _nodes(self) -> list[str]:
        room = self._room()
        return [n for n in room.nodes if n in self.coordinator.data.lights] if room else []

    def _now(self) -> dict[str, Any]:
        """The room as one light: on if any is; brightness and tone of those that are on."""
        states = [self.coordinator.reported(n) for n in self._nodes()]
        lit = [s for s in states if s["Power"]]
        some = lit or states
        return {
            "Power": bool(lit),
            "Brightness": round(sum(s["Brightness"] or 0 for s in some) / len(some)),
            "CCT": collections.Counter(s["CCT"] for s in some).most_common(1)[0][0],
        }

    @property
    def available(self) -> bool:
        return super().available and bool(self._nodes())

    @property
    def is_on(self) -> bool:
        return self._now()["Power"]

    @property
    def brightness(self) -> int:
        return to_ha(self._now()["Brightness"])

    @property
    def color_temp_kelvin(self) -> int | None:
        return self._now()["CCT"]

    @property
    def effect(self) -> str | None:
        kelvin = self._now()["CCT"]
        return next((t for t, k in TONES.items() if k == kelvin), None)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"lights": len(self._nodes())}

    async def async_turn_on(self, **kwargs: Any) -> None:
        params: dict[str, Any] = {"Power": True}
        if ATTR_BRIGHTNESS in kwargs:
            params["Brightness"] = to_oasis(kwargs[ATTR_BRIGHTNESS])
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            params["CCT"] = max(MIN_KELVIN, min(MAX_KELVIN, int(kwargs[ATTR_COLOR_TEMP_KELVIN])))
        if (effect := kwargs.get(ATTR_EFFECT)) in TONES:
            params["CCT"] = TONES[effect]
        await self._send(params)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send({"Power": False})

    async def _send(self, params: dict[str, Any]) -> None:
        nodes = self._nodes()
        if not nodes:
            raise HomeAssistantError("These Oasis lights aren't reporting")
        try:
            await self.coordinator.send(nodes, params)
        except OasisError as e:
            raise HomeAssistantError(f"Oasis: {e}") from e
