#!/usr/bin/env python3

import asyncio
import logging
import re
import shutil
from collections import defaultdict
from configparser import ConfigParser
from datetime import datetime
from json import dumps
from pathlib import Path
from random import randint
from subprocess import PIPE, Popen, run
from time import time
from typing import Dict, Optional, Tuple

from aioprometheus.collectors import Gauge, Registry
from aioprometheus.service import Service
from git.repo.base import Repo

LOG = logging.getLogger(__name__)
SHED_CONFIG_SECTION = "ansible_shed"


def _load_shed_config(config_path: Path) -> ConfigParser:
    cp = ConfigParser()
    with config_path.open("r") as cpfp:
        cp.read_file(cpfp)
    return cp


class Shed:
    ansible_stats_line_re = re.compile(r"([a-z\.0-9]*)\s+: (ok=.*)")

    def __init__(self, config_path: Path) -> None:
        self.config = _load_shed_config(config_path)
        self.config_path = config_path
        self.reload_config_vars()

        self.prom_stats: Dict[str, int] = defaultdict(int)
        self.prom_stats_update = asyncio.Event()

        # Set and create log directory
        log_dir = self.config[SHED_CONFIG_SECTION].get("log_dir")
        self.latest_log_symlink = None
        self.log_dir_path = Path(log_dir) if log_dir else None
        if self.log_dir_path:
            self.log_dir_path.mkdir(exist_ok=True, parents=True)
            self.latest_log_symlink = self.log_dir_path / "latest.log"

    def reload_config_vars(self) -> None:
        self.repo_path = Path(self.config[SHED_CONFIG_SECTION].get("repo_path", ""))
        self.init_file = (
            Path(self.config[SHED_CONFIG_SECTION]["repo_path"])
            / self.config[SHED_CONFIG_SECTION]["ansible_playbook_init"]
        )
        self.repo_url = self.config[SHED_CONFIG_SECTION].get("repo_url")
        self.run_interval_seconds = (
            self.config[SHED_CONFIG_SECTION].getint("interval", fallback=60) * 60
        )
        self.stats_port = self.config[SHED_CONFIG_SECTION].getint("port", fallback=8080)

    def _rebase_or_clone_repo(self) -> None:
        git_ssh_cmd = f"ssh -i {self.config[SHED_CONFIG_SECTION].get('repo_key')}"
        if self.init_file.exists():
            LOG.info(f"Rebasing {self.repo_path} from {self.repo_url}")
            repo = Repo(self.repo_path)
            with repo.git.custom_environment(GIT_SSH_COMMAND=git_ssh_cmd):
                repo.remotes.origin.fetch()
                repo.remotes.origin.refs.main.checkout()
            return

        # if we are at the point where init doesn't exist, git failed in the first pass
        # clear house and start again. Never hurts to start clean.
        if self.repo_path.exists():
            LOG.info("Repo is corrupted, re-cloning")
            # must use shutil because rmdir requires empty directory which is not guaranteed
            shutil.rmtree(self.repo_path)

        self.repo_path.mkdir(parents=True)
        LOG.info(f"Cloning {self.repo_url} to {self.repo_path}")

        Repo.clone_from(
            self.config[SHED_CONFIG_SECTION].get("repo_url", ""),
            self.repo_path,
            env={"GIT_SSH_COMMAND": git_ssh_cmd},
            branch="main",
        )

    def _create_logfile(self) -> Optional[Path]:
        """Create a timestamped logfile"""
        if not self.log_dir_path:
            return None

        now = datetime.now().strftime("%Y%m%d%H%M%S")
        return self.log_dir_path / f"ansible_shed_run_{now}.log"

    def _update_latest_log_symlink(self, latest_log: Path) -> None:
        if not self.latest_log_symlink:
            LOG.debug("No latest log symlink set. Returning ...")
            return

        try:
            if self.latest_log_symlink.exists():
                self.latest_log_symlink.unlink()
            self.latest_log_symlink.symlink_to(latest_log)
        except OSError:
            LOG.exception("Problem creating latest log symlink")

    def _run_ansible(self) -> Tuple[int, str]:
        """Run ansible-playbook and parse out statistics for prometheus"""
        run_log_path = self._create_logfile()

        cmd = [
            self.config[SHED_CONFIG_SECTION]["ansible_playbook_binary"],
            "--inventory",
            self.config[SHED_CONFIG_SECTION]["ansible_hosts_inventory"],
            self.config[SHED_CONFIG_SECTION]["ansible_playbook_init"],
        ]
        # Handle optional parameters
        if (
            "ansible_show_diff" in self.config[SHED_CONFIG_SECTION]
            and self.config[SHED_CONFIG_SECTION]["ansible_show_diff"]
        ):
            cmd.append("--diff")
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

        if not run_log_path:
            cp = run(cmd, stdout=PIPE, cwd=self.repo_path, encoding="utf-8")
            ansible_output = cp.stdout
            return_code = cp.returncode
        else:
            ansible_output = ""
            self._update_latest_log_symlink(run_log_path)
            with Popen(
                cmd, stderr=PIPE, stdout=PIPE, cwd=self.repo_path, encoding="utf8"
            ) as p, run_log_path.open("w", buffering=1) as lf:
                if p.stdout:
                    for output_line in p.stdout:
                        ansible_output += output_line
                        lf.write(output_line)

                if p.stderr:
                    lf.write(p.stderr.read())

            return_code = p.returncode

        runtime = int(time() - ansible_start_time)
        self.prom_stats["ansible_last_run_time"] = runtime
        LOG.info(f"Finished running ansible in {runtime}s")
        return (return_code, ansible_output)

    def parse_ansible_stats(self, ansible_output: str, returncode: int) -> None:
        LOG.info("Parsing ansible run output to update stats")
        # Clear out old stats
        for key in list(self.prom_stats.keys()):
            if key.startswith("host_"):
                del self.prom_stats[key]

        # Parse Ansible output to get stats
        for output_line in ansible_output.splitlines():
            if not (lm := self.ansible_stats_line_re.search(output_line)):
                continue

            hostname = lm.group(1)
            results = lm.group(2)
            for stat in results.split():
                k, v = stat.split("=", maxsplit=1)
                self.prom_stats[f"host_{hostname}_{k}"] = int(v)

        self.prom_stats["ansible_last_run_returncode"] = returncode
        self.prom_stats["ansible_stats_last_updated"] = int(time())
        self.prom_stats_update.set()

    async def _update_prom_stats(self) -> None:
        """Check for new stats every 30 seconds - Only run if last updated is newer"""
        prom_gauges = {
            "ansible_last_run_returncode": Gauge(
                "ansible_last_run_returncode",
                "UNIX return code of the ansible-playbook process",
                registry=self.prom_registry,
            ),
            "ansible_last_run_time": Gauge(
                "ansible_last_run_time",
                "Time in seconds it took the ansible-playbook process to execute",
                registry=self.prom_registry,
            ),
            "ansible_stats_last_updated": Gauge(
                "ansible_stats_last_updated",
                "UNIX timestamp of last time we updated the stats",
                registry=self.prom_registry,
            ),
            "ok": Gauge(
                "ansible_ok",
                "Number of 'ok' (no change) plays",
                registry=self.prom_registry,
            ),
            "changed": Gauge(
                "ansible_changed",
                "Number of 'changed' plays",
                registry=self.prom_registry,
            ),
            "unreachable": Gauge(
                "ansible_unreachable",
                "Number of inaccessible hosts",
                registry=self.prom_registry,
            ),
            "failed": Gauge(
                "ansible_failed",
                "Number of failed plays on hosts",
                registry=self.prom_registry,
            ),
            "skipped": Gauge(
                "ansible_skipped",
                "Number of skipped plays on hosts",
                registry=self.prom_registry,
            ),
            "rescued": Gauge(
                "ansible_rescued",
                "Number of rescued plays on hosts",
                registry=self.prom_registry,
            ),
            "ignored": Gauge(
                "ansible_ignored",
                "Number of ignored plays on hosts",
                registry=self.prom_registry,
            ),
        }

        while True:
            await self.prom_stats_update.wait()
            LOG.debug("Updating prometheus stats due to event being set")

            metric_count = 0
            for k, v in self.prom_stats.items():
                metric_count += 1
                if not k.startswith("host_"):
                    prom_gauges[k].set({}, v)
                    continue

                _, hostname, metric_name = k.split("_", maxsplit=2)
                prom_gauges[metric_name].set({"hostname": hostname}, v)

            LOG.info(f"Updated {metric_count} metrics")
            self.prom_stats_update.clear()

    async def prometheus_server(self) -> None:
        """Use aioprometheus to server statistics to prometheus"""
        self.prom_registry = Registry()
        self.prom_service = Service(registry=self.prom_registry)
        await self.prom_service.start(
            addr=self.config[SHED_CONFIG_SECTION].get("prometheus_bind_addr", "::"),
            port=self.stats_port,
        )
        LOG.info(f"Serving prometheus metrics on: {self.prom_service.metrics_url}")
        await self._update_prom_stats()
        await self.prom_service.stop()

    # TODO: Make coroutine cleanly exit on shutdown
    async def ansible_runner(self) -> None:
        loop = asyncio.get_running_loop()

        if "start_splay" in self.config[SHED_CONFIG_SECTION]:
            start_splay_int = self.config[SHED_CONFIG_SECTION].getint(
                "start_splay", fallback=0
            )
            if start_splay_int > 0:
                splay_time = randint(0, start_splay_int)
                LOG.info(f"Waiting for the start splay sleep of {splay_time}s")
                await asyncio.sleep(splay_time)

        while True:
            run_start_time = time()
            # Reload Config File
            self.config = await loop.run_in_executor(
                None, _load_shed_config, self.config_path
            )
            self.reload_config_vars()
            # Rebase ansible repo
            await loop.run_in_executor(None, self._rebase_or_clone_repo)
            # Run ansible playbook
            returncode, ansible_output = await loop.run_in_executor(
                None, self._run_ansible
            )
            # Parse ansible success or error
            await loop.run_in_executor(
                None, self.parse_ansible_stats, ansible_output, returncode
            )

            run_finish_time = time()
            run_time = int(run_finish_time - run_start_time)
            sleep_time = self.run_interval_seconds - run_time
            LOG.info(f"Finished ansible run in {run_time}s. Sleeping for {sleep_time}s")
            LOG.debug(f"Stats:\n{dumps(self.prom_stats, indent=2, sort_keys=True)}")
            await asyncio.sleep(sleep_time)
