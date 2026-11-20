"""Oasis's cloud: stock ESP RainMaker behind Oasis's own Cognito sign-in.

The lights have no LAN API (the Oasis app uses Bluetooth mesh nearby and this
cloud otherwise). A refresh token from a one-time Google sign-in buys access
tokens that last a day."""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import API, CLIENT_ID, LOGIN, REDIRECT


class OasisError(Exception):
    """The cloud couldn't be reached or didn't do what was asked."""


class OasisAuthError(OasisError):
    """The sign-in is expired, revoked or wrong: sign in again."""


@dataclass
class Room:
    """An Oasis room, or a light that's in none (then id is the node id and name is "")."""

    id: str
    name: str
    nodes: list[str]


@dataclass
class Light:
    id: str
    name: str
    power: bool = False
    brightness: int = 0  # 0-100
    kelvin: int | None = None


@dataclass
class Snapshot:
    rooms: list[Room] = field(default_factory=list)
    lights: dict[str, Light] = field(default_factory=dict)


def parse_sign_in(text: str) -> tuple[str, str]:
    """What the person pasted -> ("code", code) or ("token", refresh token).

    Takes the whole com.mixtiles.oasis://success?code=... address, a bare code,
    or a refresh token kept from an earlier sign-in (long)."""
    text = (text or "").strip().strip('"')
    if m := re.search(r"[?&]code=([^&#\s]+)", text):
        return "code", m.group(1)
    if len(text) > 200:
        return "token", text
    if re.fullmatch(r"[A-Za-z0-9-]{8,}", text):
        return "code", text
    raise ValueError("not a sign-in")


def account(id_token: str | None) -> tuple[str | None, str | None]:
    """(user id, email) from an id token. Read, not checked: it only names the entry."""
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return claims.get("sub"), claims.get("email")
    except (AttributeError, IndexError, ValueError):
        return None, None


class OasisApi:
    def __init__(self, session: aiohttp.ClientSession, refresh_token: str, url: str = API) -> None:
        self.session = session
        self.refresh_token = refresh_token
        self.url = url.rstrip("/")
        self.id_token: str | None = None
        self._access = ""
        self._expires = 0.0

    @classmethod
    async def _login(cls, session: aiohttp.ClientSession, form: dict[str, str]) -> dict[str, Any]:
        try:
            async with session.post(
                LOGIN, data={"client_id": CLIENT_ID, **form}, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status in (400, 401):  # invalid_grant: expired, revoked, or a used code
                    raise OasisAuthError(await resp.text())
                if resp.status >= 300:
                    raise OasisError(f"the Oasis sign-in answered {resp.status}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as e:
            raise OasisError("can't reach the Oasis sign-in") from e

    @classmethod
    async def exchange_code(cls, session: aiohttp.ClientSession, code: str) -> dict[str, Any]:
        """A finished Google sign-in's code (good for a few minutes) -> tokens."""
        tokens = await cls._login(
            session, {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT}
        )
        if not tokens.get("refresh_token"):
            raise OasisAuthError("Oasis didn't hand over a sign-in to keep")
        return tokens

    async def access(self) -> str:
        if self._expires > time.time() + 300:
            return self._access
        tokens = await self._login(
            self.session, {"grant_type": "refresh_token", "refresh_token": self.refresh_token}
        )
        self._access = tokens["access_token"]
        self._expires = time.time() + int(tokens.get("expires_in", 3600))
        self.id_token = tokens.get("id_token") or self.id_token
        return self._access

    async def call(self, method: str, path: str, body: Any = None) -> Any:
        headers = {"Authorization": f"Bearer {await self.access()}"}
        try:
            async with self.session.request(
                method, f"{self.url}{path}", json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 401:
                    self._expires = 0  # try a fresh access token next time
                    raise OasisError("Oasis refused the access token")
                if resp.status >= 300:
                    raise OasisError(f"Oasis answered {resp.status}: {(await resp.text())[:200]}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as e:
            raise OasisError("can't reach Oasis") from e

    async def rooms(self) -> list[Room]:
        """Oasis's rooms, then any light that's in none."""
        groups = (await self.call("GET", "/user/node_group?node_list=true&sub_groups=true"))["groups"]
        rooms = [
            Room(g["group_id"], g["group_name"], list(g.get("nodes") or []))
            for home in groups
            for g in home.get("sub_groups") or []
            if g.get("type") == "room"
        ]
        roomed = {n for r in rooms for n in r.nodes}
        loose = [n for home in groups for n in home.get("nodes") or [] if n not in roomed]
        return rooms + [Room(n, "", [n]) for n in dict.fromkeys(loose)]

    async def lights(self) -> dict[str, Light]:
        nodes = (await self.call("GET", "/user/nodes?node_details=true"))["node_details"]
        out = {}
        for n in nodes:
            if not any(d.get("name") == "Light" for d in (n.get("config") or {}).get("devices") or []):
                continue
            p = (n.get("params") or {}).get("Light") or {}
            out[n["id"]] = Light(
                n["id"],
                p.get("Name") or "Oasis light",
                bool(p.get("Power")),
                int(p.get("Brightness") or 0),
                p.get("CCT"),
            )
        return out

    async def set(self, nodes: list[str], params: dict[str, Any]) -> None:
        """params: any of Power (bool), Brightness (0-100), CCT (kelvin). Instant, no fade:
        how the Oasis app sends it without Bluetooth."""
        res = await self.call("PUT", "/user/nodes/params", [{"node_id": n, "payload": {"Light": params}} for n in nodes])
        failed = [r for r in res or [] if r.get("status") != "success"]
        if failed:
            raise OasisError(
                f"{len(failed)} of {len(nodes)} lights didn't take it ({failed[0].get('description', '')})"
            )
