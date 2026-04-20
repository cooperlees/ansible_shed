#!/usr/bin/env python3

from collections.abc import Mapping
from json import JSONDecodeError
from typing import Any

import aiohttp

DEFAULT_TIMEOUT_SECONDS = 10


class AnsibleShedApiClient:
    def __init__(
        self,
        base_url: str,
        api_token: str,
        session: aiohttp.ClientSession | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self._owns_session = session is None
        self._session = session or aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout_seconds)
        )

    async def __aenter__(self) -> "AnsibleShedApiClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_session:
            await self._session.close()

    async def pause(self, timestamp: str) -> dict[str, object]:
        return await self._request_json("POST", "/pause", json={"timestamp": timestamp})

    async def force_run(self) -> dict[str, object]:
        return await self._request_json("POST", "/force-run")

    async def healthz(self) -> dict[str, object]:
        return await self._request_json("GET", "/healthz")

    async def _request_json(
        self,
        method: str,
        path: str,
        json: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        headers = {"X-API-Token": self.api_token}
        url = f"{self.base_url}{path}"
        async with self._session.request(
            method, url, headers=headers, json=json
        ) as response:
            try:
                payload: dict[str, object] = await response.json()
            except (aiohttp.ContentTypeError, JSONDecodeError) as err:
                body = await response.text()
                raise RuntimeError(
                    f"Unexpected non-JSON response ({response.status}): {body}"
                ) from err

            if response.status >= 400:
                raise RuntimeError(f"HTTP {response.status}: {payload}")

            return payload
