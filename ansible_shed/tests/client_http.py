#!/usr/bin/env python3

import unittest
from json import JSONDecodeError
from typing import Any, cast

from ansible_shed.client.http import AnsibleShedApiClient


class _FakeResponse:
    def __init__(
        self,
        status: int,
        payload: dict[str, object] | None = None,
        *,
        json_error: Exception | None = None,
        body: str = "",
    ) -> None:
        self.status = status
        self._payload = payload or {}
        self._json_error = json_error
        self._body = body

    async def json(self) -> dict[str, object]:
        if self._json_error is not None:
            raise self._json_error
        return self._payload

    async def text(self) -> str:
        return self._body


class _FakeRequestContext:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def request(
        self, method: str, url: str, headers: dict[str, str], json: object = None
    ) -> _FakeRequestContext:
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "json": json}
        )
        return _FakeRequestContext(self._response)

    async def close(self) -> None:
        self.closed = True


class ClientHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_pause_request_includes_auth_header(self) -> None:
        session = _FakeSession(_FakeResponse(200, {"paused": True}))
        client = AnsibleShedApiClient(
            base_url="http://localhost:12345",
            api_token="test-token",
            session=cast(Any, session),
        )
        payload = await client.pause("1735689600")
        self.assertEqual(payload["paused"], True)
        self.assertEqual(len(session.calls), 1)
        call = session.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "http://localhost:12345/pause")
        self.assertEqual(call["headers"], {"X-API-Token": "test-token"})
        self.assertEqual(call["json"], {"timestamp": "1735689600"})

    async def test_request_json_raises_on_non_json_response(self) -> None:
        session = _FakeSession(
            _FakeResponse(
                200,
                json_error=JSONDecodeError("bad", doc="", pos=0),
                body="not-json",
            )
        )
        client = AnsibleShedApiClient(
            base_url="http://localhost:12345",
            api_token="test-token",
            session=cast(Any, session),
        )
        with self.assertRaisesRegex(RuntimeError, "Unexpected non-JSON response"):
            await client.force_run()

    async def test_request_json_raises_on_http_error(self) -> None:
        session = _FakeSession(_FakeResponse(401, {"error": "unauthorized"}))
        client = AnsibleShedApiClient(
            base_url="http://localhost:12345",
            api_token="test-token",
            session=cast(Any, session),
        )
        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            await client.force_run()

    async def test_healthz_allows_503_payload(self) -> None:
        session = _FakeSession(_FakeResponse(503, {"ok": False, "checks": {}}))
        client = AnsibleShedApiClient(
            base_url="http://localhost:12345",
            api_token="test-token",
            session=cast(Any, session),
        )
        payload = await client.healthz()
        self.assertEqual(payload["ok"], False)

    async def test_owned_session_is_closed(self) -> None:
        client = AnsibleShedApiClient(
            base_url="http://localhost:12345", api_token="test-token"
        )
        await client.close()
        self.assertTrue(client._session.closed)
