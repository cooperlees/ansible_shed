#!/usr/bin/env python3

import ipaddress
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path

from ansible_shed.constants import (
    DEFAULT_API_PORT,
    DEFAULT_API_TOKEN_PLACEHOLDER,
    SHED_CONFIG_SECTION,
)


@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    api_token: str


def _normalize_host(host: str) -> str:
    normalized_host = host.strip()
    if normalized_host.startswith("[") and normalized_host.endswith("]"):
        return normalized_host
    try:
        ip = ipaddress.ip_address(normalized_host)
    except ValueError:
        return normalized_host
    if ip.version == 6:
        return f"[{normalized_host}]"
    return normalized_host


def load_api_config(
    config_path: Path, host: str = "::1", scheme: str = "http"
) -> ApiConfig:
    cp = ConfigParser()
    with config_path.open("r") as cpfp:
        cp.read_file(cpfp)

    if SHED_CONFIG_SECTION not in cp:
        raise ValueError(f"Missing [{SHED_CONFIG_SECTION}] section in config")

    section = cp[SHED_CONFIG_SECTION]
    api_token = section.get("api_token")
    if not api_token or api_token == DEFAULT_API_TOKEN_PLACEHOLDER:
        raise ValueError(
            "api_token is not configured; set a random unique token in config"
        )

    port = section.getint("port", fallback=DEFAULT_API_PORT)
    normalized_host = _normalize_host(host)
    return ApiConfig(
        base_url=f"{scheme}://{normalized_host}:{port}", api_token=api_token
    )
