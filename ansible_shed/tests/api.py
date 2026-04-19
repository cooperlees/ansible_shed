#!/usr/bin/env python3

import asyncio
import os
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from subprocess import TimeoutExpired
from typing import cast
from unittest.mock import Mock, patch

from ansible_shed.shed import Shed


class APITests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_path = os.environ.get("PATH", "")
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_path = Path(self.test_dir.name)
        self.repo_path = self.test_path / "repo"
        self.bin_path = self.test_path / "bin"
        self.bin_path.mkdir(parents=True)
        self.repo_path.mkdir(parents=True)
        (self.repo_path / "site.yaml").write_text("---")
        (self.bin_path / "ansible-playbook").write_text("#!/bin/sh\nexit 0\n")
        (self.bin_path / "ansible-playbook").chmod(0o755)
        self.config_file = self.test_path / "test_config.ini"
        self.config_file.write_text(f"""[ansible_shed]
interval=60
port=12345
log_dir={self.test_path / "logs"}
repo_path={self.repo_path}
repo_url=git@github.com:test/test.git
repo_key={self.test_path / "key"}
ansible_playbook_binary={self.bin_path / "ansible-playbook"}
ansible_hosts_inventory=hosts
ansible_playbook_init=site.yaml
api_token=test-token
""")

    def tearDown(self) -> None:
        os.environ["PATH"] = self.original_path
        self.test_dir.cleanup()

    @patch("pathlib.Path.mkdir")
    def test_api_token_validation(self, mock_mkdir: Mock) -> None:
        shed = Shed(self.config_file)
        self.assertTrue(shed._has_valid_api_token({"X-API-Token": "test-token"}))
        self.assertFalse(shed._has_valid_api_token({"X-API-Token": "wrong"}))

    @patch("pathlib.Path.mkdir")
    def test_parse_timestamp(self, mock_mkdir: Mock) -> None:
        shed = Shed(self.config_file)
        self.assertEqual(shed._parse_timestamp_to_epoch("12345"), 12345)
        self.assertEqual(
            shed._parse_timestamp_to_epoch("2026-03-11T01:45:55Z"), 1773193555
        )
        self.assertIsNone(shed._parse_timestamp_to_epoch("bad"))

    @patch("pathlib.Path.mkdir")
    @patch("ansible_shed.shed.run")
    @patch("ansible_shed.shed.shutil.which")
    def test_healthcheck(
        self, mock_which: Mock, mock_run: Mock, mock_mkdir: Mock
    ) -> None:
        mock_which.return_value = "/usr/bin/tool"
        mock_run.return_value.returncode = 0
        shed = Shed(self.config_file)
        health = shed._healthcheck()
        self.assertEqual(health["ok"], True)

    @patch("pathlib.Path.mkdir")
    @patch("ansible_shed.shed.run")
    @patch("ansible_shed.shed.shutil.which")
    def test_healthcheck_timeout(
        self, mock_which: Mock, mock_run: Mock, mock_mkdir: Mock
    ) -> None:
        mock_which.return_value = "/usr/bin/tool"
        mock_run.side_effect = TimeoutExpired(
            cmd=["/usr/bin/tool", "--help"], timeout=5
        )
        shed = Shed(self.config_file)
        health = shed._healthcheck()
        self.assertEqual(health["ok"], False)
        checks = cast(Mapping[str, object], health["checks"])
        ansible_check = cast(Mapping[str, object], checks["ansible-playbook"])
        self.assertEqual(ansible_check["reason"], "timeout")

    @patch("pathlib.Path.mkdir")
    def test_metrics_url_for_log_ipv6(self, mock_mkdir: Mock) -> None:
        shed = Shed(self.config_file)
        self.assertEqual(shed._metrics_url_for_log("::"), "http://[::]:12345/metrics")

    @patch("pathlib.Path.mkdir")
    def test_add_ansible_binary_path_to_path(self, mock_mkdir: Mock) -> None:
        os.environ["PATH"] = "/usr/bin"
        shed = Shed(self.config_file)
        self.assertTrue(
            os.environ["PATH"].startswith(f"{self.bin_path}{os.pathsep}/usr/bin")
        )
        shed.reload_config_vars()
        self.assertEqual(os.environ["PATH"].count(str(self.bin_path)), 1)

    @patch("pathlib.Path.mkdir")
    def test_wait_for_force_run(self, mock_mkdir: Mock) -> None:
        shed = Shed(self.config_file)

        async def run_test() -> bool:
            async def set_event() -> None:
                await asyncio.sleep(0.01)
                shed.force_run_requested.set()

            set_task = asyncio.create_task(set_event())
            triggered = await shed._wait_for_force_run(1)
            await set_task
            return triggered

        self.assertTrue(asyncio.run(run_test()))
        self.assertFalse(shed.force_run_requested.is_set())
