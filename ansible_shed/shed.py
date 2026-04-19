#!/usr/bin/env python3

import asyncio
import logging
import re
import secrets
import shutil
from collections import defaultdict
from collections.abc import Mapping
from configparser import ConfigParser
from datetime import datetime, timezone
from json import dumps, JSONDecodeError, loads
from pathlib import Path
from random import randint
from subprocess import DEVNULL, PIPE, Popen, run
from time import time

import aiohttp
import aiohttp.web
from aioprometheus.collectors import Gauge, Registry
from aioprometheus.renderer import render
from git.repo.base import Repo

LOG = logging.getLogger(__name__)
SHED_CONFIG_SECTION = "ansible_shed"
DEFAULT_API_TOKEN_PLACEHOLDER = "change-me-random-token"


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

        self.prom_stats: dict[str, int] = defaultdict(int)
        self.prom_stats_update = asyncio.Event()
        self.force_run_requested = asyncio.Event()
        self.version_check_packages: list[dict[str, str]] = []
        self.paused_until_epoch: int | None = None

        # Set and create log directory
        log_dir = self.config[SHED_CONFIG_SECTION].get("log_dir")
        self.latest_log_symlink = None
        self.log_dir_path = Path(log_dir) if log_dir else None
        if self.log_dir_path:
            self.log_dir_path.mkdir(exist_ok=True, parents=True)
            self.latest_log_symlink = self.log_dir_path / "latest.log"

    def reload_config_vars(self) -> None:
        self.repo_path = Path(self.config[SHED_CONFIG_SECTION]["repo_path"])
        self.init_file = (
            Path(self.config[SHED_CONFIG_SECTION]["repo_path"])
            / self.config[SHED_CONFIG_SECTION]["ansible_playbook_init"]
        )
        self.repo_url = self.config[SHED_CONFIG_SECTION]["repo_url"]
        self.run_interval_seconds = (
            self.config[SHED_CONFIG_SECTION].getint("interval", fallback=60) * 60
        )
        self.stats_port = self.config[SHED_CONFIG_SECTION].getint(
            "port", fallback=12345
        )
        self.vault_pass_file = self.config[SHED_CONFIG_SECTION].get("vault_pass_file")
        self.version_check_state_enabled = self.config[SHED_CONFIG_SECTION].getboolean(
            "version_check_state_enabled", fallback=False
        )
        configured_api_token = self.config[SHED_CONFIG_SECTION].get("api_token")
        if configured_api_token == DEFAULT_API_TOKEN_PLACEHOLDER:
            self.api_token = None
            return
        self.api_token = configured_api_token

    def _has_valid_api_token(self, headers: Mapping[str, str]) -> bool:
        if not self.api_token:
            return False
        request_token = headers.get("X-API-Token")
        if request_token is None:
            return False
        return secrets.compare_digest(request_token, self.api_token)

    @staticmethod
    def _parse_timestamp_to_epoch(timestamp_raw: str) -> int | None:
        timestamp_str = timestamp_raw.strip()
        if not timestamp_str:
            return None
        if timestamp_str.isdigit():
            return int(timestamp_str)
        try:
            return int(
                datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).timestamp()
            )
        except ValueError:
            return None

    def _is_paused(self) -> bool:
        if self.paused_until_epoch is None:
            return False
        return int(time()) < self.paused_until_epoch

    def _healthcheck(self) -> dict[str, object]:
        checks: dict[str, dict[str, object]] = {}
        for binary_name in ("ansible-playbook", "git"):
            binary_path = shutil.which(binary_name)
            if not binary_path:
                checks[binary_name] = {"ok": False, "reason": "not found"}
                continue
            returncode = run(
                [binary_path, "--help"],
                stdout=DEVNULL,
                stderr=DEVNULL,
                check=False,
            ).returncode
            checks[binary_name] = {"ok": returncode == 0, "returncode": returncode}
        return {"ok": all(c["ok"] for c in checks.values()), "checks": checks}

    async def _wait_for_force_run(self, timeout_seconds: int) -> bool:
        if timeout_seconds <= 0:
            if not self.force_run_requested.is_set():
                return False
            self.force_run_requested.clear()
            return True
        try:
            await asyncio.wait_for(self.force_run_requested.wait(), timeout_seconds)
        except asyncio.TimeoutError:
            return False
        self.force_run_requested.clear()
        return True

    async def _handle_metrics(
        self, request: aiohttp.web.Request
    ) -> aiohttp.web.Response:
        content, http_headers = render(
            self.prom_registry, request.headers.getall("Accept", [])
        )
        return aiohttp.web.Response(body=content, headers=http_headers)

    async def _handle_pause(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        if not self._has_valid_api_token(request.headers):
            return aiohttp.web.json_response({"error": "unauthorized"}, status=401)
        try:
            body = await request.json()
        except (JSONDecodeError, aiohttp.ContentTypeError):
            body = {}

        timestamp_raw = body.get("timestamp") if isinstance(body, dict) else None
        if timestamp_raw is None:
            timestamp_raw = request.query.get("timestamp")
        if timestamp_raw is None:
            return aiohttp.web.json_response(
                {"error": "missing timestamp in JSON body or query"},
                status=400,
            )

        pause_until_epoch = self._parse_timestamp_to_epoch(str(timestamp_raw))
        if pause_until_epoch is None:
            return aiohttp.web.json_response(
                {
                    "error": "invalid timestamp format, use UNIX epoch seconds or ISO8601"
                },
                status=400,
            )
        self.paused_until_epoch = pause_until_epoch
        LOG.info(
            "Pause requested via API until "
            f"{datetime.fromtimestamp(pause_until_epoch, tz=timezone.utc).isoformat()}"
        )
        return aiohttp.web.json_response(
            {"paused_until_epoch": pause_until_epoch, "paused": self._is_paused()}
        )

    async def _handle_force_run(
        self, request: aiohttp.web.Request
    ) -> aiohttp.web.Response:
        if not self._has_valid_api_token(request.headers):
            return aiohttp.web.json_response({"error": "unauthorized"}, status=401)
        self.force_run_requested.set()
        LOG.info("Force run requested via API")
        return aiohttp.web.json_response({"status": "scheduled"})

    async def _handle_healthz(
        self, request: aiohttp.web.Request
    ) -> aiohttp.web.Response:
        if not self._has_valid_api_token(request.headers):
            return aiohttp.web.json_response({"error": "unauthorized"}, status=401)
        loop = asyncio.get_running_loop()
        health = await loop.run_in_executor(None, self._healthcheck)
        status = 200 if bool(health.get("ok")) else 503
        return aiohttp.web.json_response(health, status=status)

    def _rebase_or_clone_repo(self) -> None:
        git_ssh_cmd = f"ssh -i {self.config[SHED_CONFIG_SECTION].get('repo_key')}"
        if self.init_file.exists():
            LOG.info(f"Rebasing {self.repo_path} from {self.repo_url}")
            repo = Repo(self.repo_path)
            with repo.git.custom_environment(GIT_SSH_COMMAND=git_ssh_cmd):
                repo.remotes.origin.fetch()
                repo.remotes.origin.refs.main.checkout()
            self._setup_vault_pass()
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
            self.repo_url,
            self.repo_path,
            env={"GIT_SSH_COMMAND": git_ssh_cmd},
            branch="main",
        )

        self._setup_vault_pass()

    def _setup_vault_pass(self) -> None:
        """Copy vault password file to .vault_pass in repo if configured"""
        vault_pass_dest = self.repo_path / ".vault_pass"

        if not self.vault_pass_file:
            LOG.info("No vault_pass_file configured in config")
            return

        vault_pass_source = Path(self.vault_pass_file)
        if not vault_pass_source.exists():
            LOG.warning(
                f"Configured vault_pass_file '{self.vault_pass_file}' does not exist"
            )
            return

        LOG.info(
            f"Copying vault password file from {vault_pass_source} to {vault_pass_dest}"
        )
        shutil.copy(vault_pass_source, vault_pass_dest)
        # Set restrictive permissions (owner read/write only) for security
        vault_pass_dest.chmod(0o600)

    def _create_logfile(self) -> Path | None:
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

    def _run_ansible(self) -> tuple[int, str]:
        """Run ansible-playbook and parse out statistics for prometheus"""
        run_log_path = self._create_logfile()

        cmd = [
            self.config[SHED_CONFIG_SECTION]["ansible_playbook_binary"],
            "--inventory",
            self.config[SHED_CONFIG_SECTION]["ansible_hosts_inventory"],
            self.config[SHED_CONFIG_SECTION]["ansible_playbook_init"],
        ]
        # Add vault password file if it exists
        vault_pass_file = self.repo_path / ".vault_pass"
        if vault_pass_file.exists():
            cmd.extend(["--vault-password-file", str(vault_pass_file)])
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

    def parse_version_check_state(self) -> None:
        """Parse version_check_state.json and update prometheus stats if enabled"""
        if not self.version_check_state_enabled:
            return

        version_check_state_file = self.repo_path / "version_check_state.json"
        if not version_check_state_file.exists():
            LOG.warning(
                f"version_check_state_enabled is set but {version_check_state_file} does not exist"
            )
            return

        with version_check_state_file.open("r") as f:
            state = loads(f.read())

        results = state.get("results", [])
        self.prom_stats["version_check_state_results"] = len(results)

        checked_at_str = state.get("checked_at", "")
        if checked_at_str:
            checked_at = datetime.strptime(
                checked_at_str, "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
            self.prom_stats["version_check_state_checked_at"] = int(
                checked_at.timestamp()
            )

        self.version_check_packages = results

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
            "version_check_state_results": Gauge(
                "version_check_state_results",
                "Total number of packages needing upgrades",
                registry=self.prom_registry,
            ),
            "version_check_state_checked_at": Gauge(
                "version_check_state_checked_at",
                "Timestamp (seconds since epoch) of last version check",
                registry=self.prom_registry,
            ),
        }

        version_check_state_package_gauge = Gauge(
            "version_check_state_package",
            "Package that needs an upgrade (value=1)",
            registry=self.prom_registry,
        )
        prev_pkg_labels: list[dict[str, str]] = []

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

            current_pkg_labels: list[dict[str, str]] = []
            for pkg in self.version_check_packages:
                labels = {
                    "name": pkg["name"],
                    "current_version": pkg["current_version"],
                    "latest_version": pkg["latest_version"],
                }
                version_check_state_package_gauge.set(labels, 1)
                current_pkg_labels.append(labels)
                metric_count += 1

            # Remove gauge entries for packages no longer in the list
            for old_labels in prev_pkg_labels:
                if old_labels not in current_pkg_labels:
                    del version_check_state_package_gauge.values[old_labels]  # type: ignore[no-untyped-call]
            prev_pkg_labels = current_pkg_labels

            LOG.info(f"Updated {metric_count} metrics")
            self.prom_stats_update.clear()

    async def prometheus_server(self) -> None:
        """Use aioprometheus to server statistics to prometheus"""
        self.prom_registry = Registry()
        app = aiohttp.web.Application()
        app.router.add_route("GET", "/metrics", self._handle_metrics)
        app.router.add_route("POST", "/pause", self._handle_pause)
        app.router.add_route("POST", "/force-run", self._handle_force_run)
        app.router.add_route("POST", "/force_run", self._handle_force_run)
        app.router.add_route("GET", "/healthz", self._handle_healthz)
        runner = aiohttp.web.AppRunner(app, shutdown_timeout=2.0)
        await runner.setup()
        bind_addr = self.config[SHED_CONFIG_SECTION].get("prometheus_bind_addr", "::")
        site = aiohttp.web.TCPSite(runner, bind_addr, self.stats_port)
        await site.start()
        LOG.info(
            f"Serving prometheus metrics on: http://{bind_addr}:{self.stats_port}/metrics"
        )
        if not self.api_token:
            LOG.warning(
                "api_token is not configured or uses the default placeholder; "
                "authenticated API endpoints are unavailable"
            )
        await self._update_prom_stats()
        await runner.cleanup()

    # TODO: Make coroutine cleanly exit on shutdown
    async def ansible_runner(self) -> None:
        loop = asyncio.get_running_loop()
        force_run_once = False

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

            if self.force_run_requested.is_set():
                self.force_run_requested.clear()
                force_run_once = True

            if self._is_paused() and not force_run_once:
                if self.paused_until_epoch is not None:
                    pause_until = datetime.fromtimestamp(
                        self.paused_until_epoch, tz=timezone.utc
                    ).isoformat()
                    LOG.info(f"Paused until {pause_until}, skipping this runtime")
                force_run_once = await self._wait_for_force_run(
                    self.run_interval_seconds
                )
                if force_run_once:
                    LOG.info("Force run requested while paused; running once")
                continue
            force_run_once = False
            # Rebase ansible repo
            await loop.run_in_executor(None, self._rebase_or_clone_repo)
            # Run ansible playbook
            returncode, ansible_output = await loop.run_in_executor(
                None, self._run_ansible
            )
            # Parse version check state before ansible stats because
            # parse_ansible_stats sets the prom_stats_update event that
            # triggers _update_prom_stats to export metrics.
            await loop.run_in_executor(None, self.parse_version_check_state)
            # Parse ansible success or error (sets prom_stats_update event)
            await loop.run_in_executor(
                None, self.parse_ansible_stats, ansible_output, returncode
            )

            run_finish_time = time()
            run_time = int(run_finish_time - run_start_time)
            if run_time > self.run_interval_seconds:
                LOG.warning(
                    "Ansible run exceeded configured interval by "
                    f"{run_time - self.run_interval_seconds}s"
                )
            sleep_time = max(self.run_interval_seconds - run_time, 0)
            LOG.info(f"Finished ansible run in {run_time}s. Sleeping for {sleep_time}s")
            LOG.debug(f"Stats:\n{dumps(self.prom_stats, indent=2, sort_keys=True)}")
            force_run_once = await self._wait_for_force_run(sleep_time)
            if force_run_once:
                LOG.info("Force run requested; starting next run now")
