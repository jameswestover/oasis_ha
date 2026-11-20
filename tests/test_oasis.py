import time

import pytest
from homeassistant import config_entries
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from homeassistant.util import dt as dt_util
from datetime import timedelta

from custom_components.oasis.api import parse_sign_in
from custom_components.oasis.const import CONF_REFRESH_TOKEN, DOMAIN

TOKEN = "good-refresh-" + "x" * 300
CODE = "11111111-2222-3333-4444-555555555555"


async def setup(hass, token=TOKEN):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="user-1", title="someone@example.com", data={CONF_REFRESH_TOKEN: token})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def light_ids(hass):
    reg = er.async_get(hass)
    return {e.unique_id: e.entity_id for e in reg.entities.values() if e.platform == DOMAIN}


def test_parse_sign_in():
    assert parse_sign_in(f"com.mixtiles.oasis://success?code={CODE}") == ("code", CODE)
    assert parse_sign_in(f"  {CODE} ") == ("code", CODE)
    assert parse_sign_in(TOKEN) == ("token", TOKEN)
    with pytest.raises(ValueError):
        parse_sign_in("hello there")


async def test_sign_in_with_the_address(hass: HomeAssistant, oasis):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"sign_in": f"com.mixtiles.oasis://success?code={CODE}"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "someone@example.com"
    assert result["data"] == {CONF_REFRESH_TOKEN: TOKEN}
    assert result["result"].unique_id == "user-1"


async def test_sign_in_with_a_kept_token_and_used_code(hass: HomeAssistant, oasis):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"sign_in": "bad-" + "y" * 300})
    assert result["errors"] == {"sign_in": "invalid_token"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"sign_in": "99999999-0000"})
    assert result["errors"] == {"sign_in": "code_expired"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"sign_in": TOKEN})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "user-1"


async def test_rooms_become_lights_in_their_area(hass: HomeAssistant, oasis):
    await setup(hass)
    ids = light_ids(hass)
    assert set(ids) == {"g1", "n3"}
    room = hass.states.get(ids["g1"])
    assert room.state == STATE_ON
    assert room.attributes["brightness"] == 153  # 60% (only the light that's on counts)
    assert room.attributes["color_temp_kelvin"] == 1800
    assert room.attributes["effect"] == "Candle"
    assert room.attributes["friendly_name"] == "Oasis lights"
    loose = hass.states.get(ids["n3"])
    assert loose.state == STATE_OFF and loose.attributes["friendly_name"] == "Hall light"
    device = dr.async_get(hass).async_get_device({(DOMAIN, "g1")})
    assert ar.async_get(hass).async_get_area(device.area_id).name == "Living Room"


async def test_actions_send_and_hold_until_reported(hass: HomeAssistant, oasis):
    await setup(hass)
    entity = light_ids(hass)["g1"]
    await hass.services.async_call("light", "turn_on", {"entity_id": entity, "effect": "Maui", "brightness": 255}, blocking=True)
    assert oasis.sent[-1] == [
        {"node_id": n, "payload": {"Light": {"Power": True, "Brightness": 100, "CCT": 1100}}} for n in ("n1", "n2")
    ]
    # The cloud still reports the old setting; the light keeps showing what was sent.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    state = hass.states.get(entity)
    assert state.attributes["effect"] == "Maui" and state.attributes["brightness"] == 255

    await hass.services.async_call("light", "turn_on", {"entity_id": entity, "color_temp_kelvin": 9000}, blocking=True)
    assert oasis.sent[-1][0]["payload"]["Light"] == {"Power": True, "CCT": 4000}
    await hass.services.async_call("light", "turn_off", {"entity_id": entity}, blocking=True)
    assert oasis.sent[-1][0]["payload"]["Light"] == {"Power": False}
    assert hass.states.get(entity).state == STATE_OFF


async def test_settled_send_expires(hass: HomeAssistant, oasis, monkeypatch):
    entry = await setup(hass)
    entity = light_ids(hass)["g1"]
    await hass.services.async_call("light", "turn_off", {"entity_id": entity}, blocking=True)
    coordinator = entry.runtime_data
    later = time.time() + 25
    monkeypatch.setattr("custom_components.oasis.coordinator.time.time", lambda: later)
    await coordinator.async_refresh()
    assert hass.states.get(entity).state == STATE_ON  # the lights never took it: show what they report


async def test_expired_sign_in_asks_again(hass: HomeAssistant, oasis):
    entry = await setup(hass, token="expired-" + "z" * 300)
    assert entry.state is config_entries.ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]
    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"sign_in": CODE})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == TOKEN

