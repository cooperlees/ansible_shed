#!/usr/bin/env python3

import asyncio
import logging
import os
from configparser import ConfigParser
from collections import defaultdict
from json import dumps
from pathlib import Path
from random import randint
from subprocess import CompletedProcess, PIPE, run
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

    def _run_ansible(self) -> CompletedProcess:
        """Run ansible-playbook and parse out statistics for prometheus"""
        os.chdir(str(self.repo_path.parent))
        cmd = [
            self.config[SHED_CONFIG_SECTION]["ansible_playbook_binary"],
            "--inventory",
            self.config[SHED_CONFIG_SECTION]["ansible_hosts_inventory"],
            self.config[SHED_CONFIG_SECTION]["ansible_playbook_init"],
        ]
        # Handle optional parameters
        if (
            "ansible_limit" in self.config[SHED_CONFIG_SECTION]
            and self.config[SHED_CONFIG_SECTION]["ansible_limit"]
        ):
            cmd.extend(["--limit", self.config[SHED_CONFIG_SECTION]["ansible_limit"]])
        if (
            "ansible_tags" in self.config[SHED_CONFIG_SECTION]
            and self.config[SHED_CONFIG_SECTION]["ansible_tags"]
        ):
            cmd.extend(["--tags", self.config[SHED_CONFIG_SECTION]["ansible_tags"]])
        if (
            "ansible_skip_tags" in self.config[SHED_CONFIG_SECTION]
            and self.config[SHED_CONFIG_SECTION]["ansible_skip_tags"]
        ):
            cmd.extend(
                ["--skip-tags", self.config[SHED_CONFIG_SECTION]["ansible_skip_tags"]]
            )
        LOG.info(f"Running ansible-playbook: '{' '.join(cmd)}'")
        ansible_start_time = time()
        cp = run(cmd, stdout=PIPE)
        runtime = int(time() - ansible_start_time)
        self.prom_stats["ansible_run_time"] = runtime
        LOG.info(f"Finished running ansible in {runtime}s")
        return cp

    async def prometheus_server(self) -> None:
        """Use aioprometheus to server statistics to prometheus"""
        pass

    def parse_ansible_stats(self, cp: CompletedProcess) -> None:
        LOG.info("Parsing ansible run output to update stats")
        self.prom_stats["last_run_returncode"] = cp.returncode
        self.prom_stats["ansible_stats_last_updated"] = int(time())

    # TODO: Make coroutine cleanly exit on shutdown
    async def ansible_runner(self) -> None:
        loop = asyncio.get_running_loop()

        if "start_splay" in self.config[SHED_CONFIG_SECTION]:
            start_splay_int = self.config[SHED_CONFIG_SECTION].getint("start_splay")
            if start_splay_int > 0:
                splay_time = randint(0, start_splay_int)
                LOG.info(f"Waiting for the start splay sleep of {splay_time}s")
                await asyncio.sleep(splay_time)

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
            LOG.debug(f"Stats:\n{dumps(self.prom_stats, indent=2, sort_keys=True)}")
            await asyncio.sleep(sleep_time)
