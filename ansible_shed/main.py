#!/usr/bin/env python3

import asyncio
import logging
import os
import sys
from pathlib import Path
from subprocess import run
from time import time
from typing import Any, Dict, Union

import click


LOG = logging.getLogger(__name__)


class Shed:
    def __init__(
        self, interval: int, repo_path: str, repo_url: str, port: int = 12345
    ) -> None:
        self.run_interval_seconds = interval * 60
        self.repo_path = Path(repo_path)
        self.repo_url = repo_url
        self.stats_port = port
        self.prom_stats: Dict[str, int] = {}

    def _rebase_or_clone_repo(self) -> None:
        if self.repo_path.exists():
            LOG.info(f"Rebasing {self.repo_path} from {self.repo_url}")
            run(["/usr/bin/git", "pull", "--rebase"])
            return

        LOG.info(f"Cloning {self.repo_url} to {self.repo_path}")
        os.chdir(str(self.repo_path.parent))
        run(["/usr/bin/git", "clone", self.repo_url])

    def _run_ansible(self, repo_local_path: Path) -> None:
        """Run ansible-playbook and parse out statistics for prometheus"""
        pass

    async def prometheus_server(self) -> None:
        """Use aioprometheus to server statistics to prometheus"""
        pass

    # TODO: Make coroutine cleanly exit on shutdown
    async def ansible_runner(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            run_start_time = time()
            # Rebase ansible repo
            await loop.run_in_executor(None, self._rebase_or_clone_repo)
            # Run ansible playbook
            await loop.run_in_executor(None, self._run_ansible)

            # TODO: Collect stats and have ready for prometheus to collect

            run_finish_time = time()
            run_time = int(run_finish_time - run_start_time)
            sleep_time = self.run_interval_seconds - run_time
            LOG.info(f"Finished ansible run in {run_time}s. Sleeping for {sleep_time}s")
            await asyncio.sleep(sleep_time)


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


async def async_main(
    debug: bool, interval: int, port: int, repo_path: str, repo_url: str
) -> int:
    # TODO: Signal handlers + cleanup
    s = Shed(interval, repo_path, repo_url, port)
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
    "-i",
    "--interval",
    default=60,
    show_default=True,
    help="Shed run intervals (minutes between runs)",
)
@click.option(
    "-p",
    "--port",
    default=12345,
    type=int,
    show_default=True,
    help="Port for prometheus exporter",
)
@click.option(
    "-R",
    "--repo-path",
    default=os.getcwd(),
    show_default=True,
    help="Path to store repo locally",
)
@click.option(
    "-r",
    "--repo-url",
    default="git@github.com:cooperlees/clc_ansible.git",
    show_default=True,
    help="URL of ansible repo",
)
@click.pass_context
def main(ctx: click.core.Context, **kwargs: Any) -> None:
    LOG.debug(f"Starting {sys.argv[0]}")
    ctx.exit(asyncio.run(async_main(**kwargs)))


if __name__ == "__main__":
    main()
