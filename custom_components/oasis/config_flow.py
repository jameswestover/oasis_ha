"""Signing in to Oasis: Google, Apple, or email and password, like the Oasis app.

Email and password sign in right in the form (and are kept, so the integration
can sign in again by itself). Google and Apple return to the Oasis app's own
address (com.mixtiles.oasis://success?code=...), which nothing but that app can
catch, so the form gives the sign-in link and takes back that address (or its
code). Any of them also takes a refresh token kept from an earlier sign-in."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import OasisApi, OasisAuthError, OasisError, account, parse_sign_in
from .const import CONF_EMAIL, CONF_PASSWORD, CONF_REFRESH_TOKEN, DOMAIN, authorize

METHODS = ["email", "google", "apple"]
LINK_SCHEMA = vol.Schema({vol.Required("sign_in"): str})


class OasisConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=METHODS)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="reauth_confirm", menu_options=METHODS)

    async def async_step_email(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        email = (user_input or {}).get(CONF_EMAIL) or (
            self._get_reauth_entry().data.get(CONF_EMAIL, "") if self.source == SOURCE_REAUTH else ""
        )
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                tokens = await OasisApi.password_sign_in(session, email.strip(), user_input[CONF_PASSWORD])
                result = await self._finish(tokens["refresh_token"], tokens.get("id_token"),
                                            {CONF_EMAIL: email.strip(), CONF_PASSWORD: user_input[CONF_PASSWORD]})
                if result:
                    return result
                errors["base"] = "cannot_connect"
            except OasisAuthError as e:
                errors["base"] = "wrong_password"
                self._reason = str(e)
            except OasisError:
                errors["base"] = "cannot_connect"
        schema = vol.Schema({
            vol.Required(CONF_EMAIL, default=email): TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL)),
            vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
        })
        return self.async_show_form(step_id="email", data_schema=schema, errors=errors,
                                    description_placeholders={"reason": getattr(self, "_reason", "")})

    async def async_step_google(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._link("google", user_input)

    async def async_step_apple(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._link("apple", user_input)

    async def _link(self, provider: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        """Google or Apple: the person signs in in a browser and pastes back where it stopped."""
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                kind, value = parse_sign_in(user_input["sign_in"])
            except ValueError:
                errors["sign_in"] = "not_sign_in"
            else:
                try:
                    if kind == "code":
                        tokens = await OasisApi.exchange_code(session, value)
                        token, id_token = tokens["refresh_token"], tokens.get("id_token")
                    else:
                        token, id_token = value, None
                    result = await self._finish(token, id_token, {})
                    if result:
                        return result
                    errors["base"] = "cannot_connect"
                except OasisAuthError:
                    errors["sign_in"] = "code_expired" if kind == "code" else "invalid_token"
                except OasisError:
                    errors["base"] = "cannot_connect"
        return self.async_show_form(step_id=provider, data_schema=LINK_SCHEMA, errors=errors,
                                    description_placeholders={"url": authorize(provider)})

    async def _finish(self, token: str, id_token: str | None, extra: dict[str, str]) -> ConfigFlowResult | None:
        """Check the sign-in works, then make (or, signing in again, update) the entry."""
        api = OasisApi(async_get_clientsession(self.hass), token)
        await api.access()
        await api.lights()
        user, email = account(id_token or api.id_token)
        data = {CONF_REFRESH_TOKEN: token, **extra}
        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            if user and entry.unique_id and user != entry.unique_id:
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(entry, data=data)
        await self.async_set_unique_id(user or token[-32:])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=email or extra.get(CONF_EMAIL) or "Oasis", data=data)
