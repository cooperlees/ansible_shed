#!/usr/bin/env python3

import ansible_runner
import asyncio
import logging
import os
import sys
from typing import Any, Union

import click


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


async def prometheus_server(port: int) -> int:
    return 0


async def ansible_periodic_runner() -> int:
    return 0


async def async_main(debug: bool, port: int) -> int:
    try:
        return_vals = await asyncio.gather(prometheus_server(port), ansible_runner())
    except KeyboardInterrupt:
        return -1
    return sum(return_vals)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--debug",
    is_flag=True,
    callback=_handle_debug,
    show_default=True,
    help="Turn on debug logging",
)
@click.option(
    "-i",
    "--interval",
    default=60,
    show_default=True,
    help="Shed run intervals (minutes between runs)",
)
@click.option(
    "-P",
    "--playbook-path",
    default=os.getcwd(),
    show_default=True,
    help="Port for prometheus exporter",
)
@click.option(
    "-p",
    "--port",
    default=1234,
    show_default=True,
    help="Port for prometheus exporter",
)
@click.pass_context
def main(ctx: click.core.Context, **kwargs: Any) -> None:
    LOG.debug(f"Starting {sys.argv[0]}")
    ctx.exit(asyncio.run(async_main(**kwargs)))


if __name__ == "__main__":
    main()
