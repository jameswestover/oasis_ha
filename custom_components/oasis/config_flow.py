"""Signing in to Oasis.

Oasis's Google sign-in only returns to the Oasis app's own address
(com.mixtiles.oasis://success?code=...), which nothing but that app can catch.
So the form gives the sign-in link and takes back that address (or its code),
or a refresh token kept from an earlier sign-in."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OasisApi, OasisAuthError, OasisError, account, parse_sign_in
from .const import AUTHORIZE, CONF_REFRESH_TOKEN, DOMAIN

SCHEMA = vol.Schema({vol.Required("sign_in"): str})


class OasisConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _check(self, text: str) -> tuple[dict[str, str], dict[str, Any]]:
        """-> (errors, entry data with the account's id and email)."""
        session = async_get_clientsession(self.hass)
        try:
            kind, value = parse_sign_in(text)
        except ValueError:
            return {"sign_in": "not_sign_in"}, {}
        try:
            if kind == "code":
                tokens = await OasisApi.exchange_code(session, value)
                token, id_token = tokens["refresh_token"], tokens.get("id_token")
            else:
                token = value
            api = OasisApi(session, token)
            await api.access()
            if kind == "token":
                id_token = api.id_token
            await api.lights()
        except OasisAuthError:
            return {"sign_in": "code_expired" if kind == "code" else "invalid_token"}, {}
        except OasisError:
            return {"base": "cannot_connect"}, {}
        user, email = account(id_token)
        return {}, {CONF_REFRESH_TOKEN: token, "user": user, "email": email}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, data = await self._check(user_input["sign_in"])
            if not errors:
                await self.async_set_unique_id(data["user"] or data[CONF_REFRESH_TOKEN][-32:])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=data["email"] or "Oasis", data={CONF_REFRESH_TOKEN: data[CONF_REFRESH_TOKEN]})
        return self.async_show_form(
            step_id="user", data_schema=SCHEMA, errors=errors, description_placeholders={"url": AUTHORIZE}
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, data = await self._check(user_input["sign_in"])
            if not errors:
                entry = self._get_reauth_entry()
                if data["user"] and entry.unique_id and data["user"] != entry.unique_id:
                    return self.async_abort(reason="wrong_account")
                return self.async_update_reload_and_abort(entry, data={CONF_REFRESH_TOKEN: data[CONF_REFRESH_TOKEN]})
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=SCHEMA, errors=errors, description_placeholders={"url": AUTHORIZE}
        )
