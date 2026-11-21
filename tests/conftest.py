"""A fake Oasis cloud (sign-in and RainMaker) for the tests."""

import base64
import json
import re

import pytest

from custom_components.oasis.const import API, LOGIN, LOGIN_PAGE, REDIRECT, SIGN_IN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def id_token(sub="user-1", email="someone@example.com"):
    body = base64.urlsafe_b64encode(json.dumps({"sub": sub, "email": email}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


class FakeOasis:
    def __init__(self):
        self.refresh = {"good-refresh-" + "x" * 300}
        self.codes = {"11111111-2222-3333-4444-555555555555"}
        self.nodes = {
            "n1": {"Name": "Oasis 1", "Power": True, "Brightness": 60, "CCT": 1800},
            "n2": {"Name": "Oasis 2", "Power": False, "Brightness": 20, "CCT": 1800},
            "n3": {"Name": "Hall light", "Power": False, "Brightness": 50, "CCT": 4000},
        }
        self.rooms = [{"group_id": "g1", "group_name": "Living Room", "type": "room", "nodes": ["n1", "n2"]}]
        self.sent = []
        self.room_calls = 0
        self.accounts = {"someone@example.com": "right-password"}
        self.login_error = ""

    def install(self, aioclient_mock):
        aioclient_mock.post(LOGIN, side_effect=self.login)
        aioclient_mock.get(re.compile(re.escape(API) + r"/user/nodes\?.*"), side_effect=self.get_nodes)
        aioclient_mock.get(re.compile(re.escape(API) + r"/user/node_group.*"), side_effect=self.get_groups)
        aioclient_mock.put(f"{API}/user/nodes/params", side_effect=self.put_params)
        aioclient_mock.get(re.compile(re.escape(SIGN_IN) + r"/login\?"), side_effect=self.login_page)
        aioclient_mock.post(re.compile(re.escape(SIGN_IN) + r"/login\?"), side_effect=self.login_form)

    async def login_page(self, method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        error = f'<p style="white-space: pre-line" id="loginErrorMessage" class="errorMessage-customizable">{self.login_error}</p>'
        page = f'<form><input type="hidden" name="_csrf" value="csrf-1"/>{error if self.login_error else ""}</form>'
        return AiohttpClientMockResponse(method, url, text=page, cookies={"XSRF-TOKEN": "csrf-1"})

    async def login_form(self, method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        assert data["_csrf"] == "csrf-1"
        if self.accounts.get(data["username"]) == data["password"]:
            code = "22222222-3333-4444-5555-666666666666"
            self.codes.add(code)
            return AiohttpClientMockResponse(method, url, status=302, headers={"Location": f"{REDIRECT}?code={code}"})
        self.login_error = "Incorrect username or password."
        return AiohttpClientMockResponse(method, url, status=302, headers={"Location": LOGIN_PAGE},
                                         cookies={"cognito-fl": "flash"})

    async def login(self, method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        if data.get("grant_type") == "authorization_code" and data.get("code") in self.codes:
            self.codes.discard(data["code"])
            body = {"refresh_token": "good-refresh-" + "x" * 300, "access_token": "a", "id_token": id_token(), "expires_in": 86400}
        elif data.get("grant_type") == "refresh_token" and data.get("refresh_token") in self.refresh:
            body = {"access_token": "a", "id_token": id_token(), "expires_in": 86400}
        else:
            return AiohttpClientMockResponse(method, url, status=400, json={"error": "invalid_grant"})
        return AiohttpClientMockResponse(method, url, json=body)

    async def get_nodes(self, method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        details = [{"id": i, "config": {"devices": [{"name": "Light"}]}, "params": {"Light": dict(p)}} for i, p in self.nodes.items()]
        details.append({"id": "hub", "config": {"devices": [{"name": "Bridge"}]}, "params": {}})
        return AiohttpClientMockResponse(method, url, json={"node_details": details})

    async def get_groups(self, method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        self.room_calls += 1
        home = {"group_id": "home", "type": "home", "nodes": list(self.nodes), "sub_groups": self.rooms}
        return AiohttpClientMockResponse(method, url, json={"groups": [home]})

    async def put_params(self, method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        self.sent.append(data)
        return AiohttpClientMockResponse(method, url, json=[{"node_id": d["node_id"], "status": "success"} for d in data])


@pytest.fixture
def oasis(aioclient_mock):
    fake = FakeOasis()
    fake.install(aioclient_mock)
    return fake
