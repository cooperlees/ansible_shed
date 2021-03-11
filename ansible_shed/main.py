#!/usr/bin/env python3

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Union

import click
from ansible_shed.shed import Shed


LOG = logging.getLogger(__name__)


def _handle_debug(
    ctx: click.core.Context,
    param: Union[click.core.Option, click.core.Parameter],
    debug: Union[bool, int, str],
) -> Union[bool, int, str]:
    """Turn on debugging if asked otherwise INFO default"""
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        format="[%(asctime)s] %(levelname)s: %(message)s (%(filename)s:%(lineno)d)",
        level=log_level,
    )
    return debug


async def async_main(debug: bool, config: str) -> int:
    if not config:
        LOG.error("Please pass a config so we can do great things!")
        return 69

    config_path = Path(config)
    if not config_path.exists():
        LOG.error(f"{config} does not exist.")
        return 1

    # TODO: Signal handlers + cleanup
    s = Shed(config_path)
    await asyncio.gather(s.prometheus_server(), s.ansible_runner())
    return 0


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--debug",
    is_flag=True,
    callback=_handle_debug,
    show_default=True,
    help="Turn on debug logging",
)
@click.option(
    "--config",
    default="/etc/ansible_shed.ini",
    show_default=True,
    help="Path to ansible shed configuration",
)
@click.pass_context
def main(ctx: click.core.Context, **kwargs: Any) -> None:
    LOG.debug(f"Starting {sys.argv[0]}")
    ctx.exit(asyncio.run(async_main(**kwargs)))


if __name__ == "__main__":
    main()
