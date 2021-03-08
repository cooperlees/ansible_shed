#!/usr/bin/env python3

import asyncio
import logging
import os
from configparser import ConfigParser
from collections import defaultdict
from pathlib import Path
from subprocess import CompletedProcess, run
from time import time
from typing import Dict


LOG = logging.getLogger(__name__)
SHED_CONFIG_SECTION = "ansible_shed"


class Shed:
    def __init__(self, config: ConfigParser) -> None:
        self.config = config
        self.prom_stats: Dict[str, int] = defaultdict(int)
        self.repo_path = Path(config[SHED_CONFIG_SECTION].get("repo_path"))
        self.repo_url = config[SHED_CONFIG_SECTION].get("repo_url")
        self.run_interval_seconds = config[SHED_CONFIG_SECTION].getint("interval") * 60
        self.stats_port = config[SHED_CONFIG_SECTION].getint("port")

    def _rebase_or_clone_repo(self) -> None:
        if self.repo_path.exists():
            LOG.info(f"Rebasing {self.repo_path} from {self.repo_url}")
            run(["/usr/bin/git", "pull", "--rebase"])
            return

        LOG.info(f"Cloning {self.repo_url} to {self.repo_path}")
        os.chdir(str(self.repo_path.parent))
        run(["/usr/bin/git", "clone", self.repo_url])

    def _run_ansible(self, repo_local_path: Path) -> CompletedProcess:
        """Run ansible-playbook and parse out statistics for prometheus"""
        cmd = ["/home/cooper/venvs/a/bin/ansible-playbook", "--help"]
        LOG.info(f"Running ansbible: {' '.join(cmd)}")
        return run(cmd, shell=True)

    async def prometheus_server(self) -> None:
        """Use aioprometheus to server statistics to prometheus"""
        pass

    def parse_ansible_stats(self, cp: CompletedProcess) -> None:
        LOG.info("Parsing ansible run output to update stats")
        self.prom_stats["last_run_returncode"] = cp.returncode

    # TODO: Make coroutine cleanly exit on shutdown
    async def ansible_runner(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            run_start_time = time()
            # Rebase ansible repo
            await loop.run_in_executor(None, self._rebase_or_clone_repo)
            # Run ansible playbook
            cp = await loop.run_in_executor(None, self._run_ansible)
            # Parse ansible success or error
            await loop.run_in_executor(None, self.parse_ansible_stats, cp)

            run_finish_time = time()
            run_time = int(run_finish_time - run_start_time)
            sleep_time = self.run_interval_seconds - run_time
            LOG.info(f"Finished ansible run in {run_time}s. Sleeping for {sleep_time}s")
            await asyncio.sleep(sleep_time)
