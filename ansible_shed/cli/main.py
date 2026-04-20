#!/usr/bin/env python3

import asyncio
from json import dumps
from pathlib import Path

import click
import click.core

from ansible_shed.client import AnsibleShedApiClient, load_api_config


def _emit_json(payload: dict[str, object]) -> None:
    click.echo(dumps(payload, sort_keys=True, indent=2))


async def _run_command(
    config: Path,
    base_url: str | None,
    action: str,
    timestamp: str | None = None,
) -> int:
    try:
        loaded = (
            load_api_config(config) if base_url is None else load_api_config(config)
        )
    except ValueError as err:
        raise click.ClickException(str(err)) from err

    resolved_base_url = base_url or loaded.base_url
    async with AnsibleShedApiClient(
        base_url=resolved_base_url, api_token=loaded.api_token
    ) as client:
        if action == "pause":
            if timestamp is None:
                raise click.ClickException("timestamp is required for pause")
            payload = await client.pause(timestamp=timestamp)
            _emit_json(payload)
            return 0
        if action == "force-run":
            payload = await client.force_run()
            _emit_json(payload)
            return 0
        if action == "healthz":
            payload = await client.healthz()
            _emit_json(payload)
            return 0 if bool(payload.get("ok")) else 1
        raise click.ClickException(f"unknown action: {action}")


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
    help="Optional API base URL override (example: http://127.0.0.1:12345)",
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
    help="UNIX epoch seconds or ISO8601 timestamp",
)
@click.pass_context
def pause(ctx: click.core.Context, timestamp: str) -> None:
    obj = ctx.obj if ctx.obj is not None else {}
    config = obj.get("config", Path("/etc/ansible_shed.ini"))
    base_url = obj.get("base_url")
    exit_code = asyncio.run(
        _run_command(
            config=config, base_url=base_url, action="pause", timestamp=timestamp
        )
    )
    ctx.exit(exit_code)


@main.command("force-run")
@click.pass_context
def force_run(ctx: click.core.Context) -> None:
    obj = ctx.obj if ctx.obj is not None else {}
    config = obj.get("config", Path("/etc/ansible_shed.ini"))
    base_url = obj.get("base_url")
    exit_code = asyncio.run(
        _run_command(config=config, base_url=base_url, action="force-run")
    )
    ctx.exit(exit_code)


@main.command("healthz")
@click.pass_context
def healthz(ctx: click.core.Context) -> None:
    obj = ctx.obj if ctx.obj is not None else {}
    config = obj.get("config", Path("/etc/ansible_shed.ini"))
    base_url = obj.get("base_url")
    exit_code = asyncio.run(
        _run_command(config=config, base_url=base_url, action="healthz")
    )
    ctx.exit(exit_code)


if __name__ == "__main__":  # pragma: no cover
    main()
