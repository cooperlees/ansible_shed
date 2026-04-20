#!/usr/bin/env python3

import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, UTC
from json import dumps
from pathlib import Path

import click
import click.core

from ansible_shed.client import AnsibleShedApiClient, load_api_config


def _emit_json(payload: dict[str, object]) -> None:
    click.echo(dumps(payload, sort_keys=True, indent=2))


_IN_TIME_RE = re.compile(r"^in\s+(\d+)\s*([smhd])$")


def _normalize_pause_timestamp(timestamp: str) -> str:
    match = _IN_TIME_RE.match(timestamp.strip().lower())
    if not match:
        return timestamp
    amount = int(match.group(1))
    unit = match.group(2)
    unit_to_delta = {
        "s": timedelta(seconds=amount),
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
    }
    pause_until = datetime.now(UTC) + unit_to_delta[unit]
    return str(int(pause_until.timestamp()))


async def _run_command(
    config: Path,
    base_url: str | None,
    operation: Callable[[AnsibleShedApiClient], Awaitable[dict[str, object]]],
) -> dict[str, object]:
    try:
        loaded = load_api_config(config)
    except (OSError, ValueError) as err:
        raise click.ClickException(str(err)) from err

    resolved_base_url = base_url or loaded.base_url
    try:
        async with AnsibleShedApiClient(
            base_url=resolved_base_url, api_token=loaded.api_token
        ) as client:
            return await operation(client)
    except click.ClickException:
        raise
    except RuntimeError as err:
        raise click.ClickException(str(err)) from err
    except Exception as err:
        raise click.ClickException(str(err)) from err


def _get_context_options(ctx: click.core.Context) -> tuple[Path, str | None]:
    obj = ctx.obj
    if not isinstance(obj, dict):
        raise click.ClickException("CLI context is invalid")
    config = obj.get("config", Path("/etc/ansible_shed.ini"))
    base_url = obj.get("base_url")
    return config, base_url


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--config",
    default="/etc/ansible_shed.ini",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Path to ansible shed configuration",
)
@click.option(
    "--base-url",
    default=None,
    help="Optional API base URL override (example: http://[::1]:12345)",
)
@click.pass_context
def main(ctx: click.core.Context, config: Path, base_url: str | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config"] = config
    ctx.obj["base_url"] = base_url


@main.command("pause")
@click.option(
    "--timestamp",
    required=True,
    help=(
        "UNIX epoch seconds, ISO8601 timestamp, or relative format (example: in 30m)"
    ),
)
@click.pass_context
def pause(ctx: click.core.Context, timestamp: str) -> None:
    config, base_url = _get_context_options(ctx)
    normalized_timestamp = _normalize_pause_timestamp(timestamp)
    payload = asyncio.run(
        _run_command(
            config=config,
            base_url=base_url,
            operation=lambda client: client.pause(timestamp=normalized_timestamp),
        )
    )
    _emit_json(payload)


@main.command("force-run")
@click.pass_context
def force_run(ctx: click.core.Context) -> None:
    config, base_url = _get_context_options(ctx)
    payload = asyncio.run(
        _run_command(
            config=config,
            base_url=base_url,
            operation=lambda client: client.force_run(),
        )
    )
    _emit_json(payload)


@main.command("healthz")
@click.pass_context
def healthz(ctx: click.core.Context) -> None:
    config, base_url = _get_context_options(ctx)
    payload = asyncio.run(
        _run_command(
            config=config,
            base_url=base_url,
            operation=lambda client: client.healthz(),
        )
    )
    _emit_json(payload)
    ctx.exit(0 if bool(payload.get("ok")) else 1)


if __name__ == "__main__":  # pragma: no cover
    main()
