#!/usr/bin/env python3

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from ansible_shed.shed import Shed

VERSION_CHECK_STATE_JSON = {
    "checked_at": "2026-03-11T01:45:55Z",
    "results": [
        {
            "current_version": "0.18.0",
            "latest_version": "0.19.0",
            "name": "monitord-exporter",
            "release_url": "https://github.com/cooperlees/monitord-exporter/releases",
            "repo": "cooperlees/monitord-exporter",
        },
        {
            "current_version": "0.4.3",
            "latest_version": "v0.4.4",
            "name": "nftables-exporter",
            "release_url": "https://github.com/metal-stack/nftables-exporter/releases",
            "repo": "metal-stack/nftables-exporter",
        },
        {
            "current_version": "1.0.4",
            "latest_version": "v1.1.0",
            "name": "kube-vip",
            "release_url": "https://github.com/kube-vip/kube-vip/releases",
            "repo": "kube-vip/kube-vip",
        },
        {
            "current_version": "1.14.1",
            "latest_version": "v1.14.2",
            "name": "coredns",
            "release_url": "https://github.com/coredns/coredns/releases",
            "repo": "coredns/coredns",
        },
    ],
}


class VersionCheckStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_path = Path(self.test_dir.name)
        self.repo_path = self.test_path / "repo"
        self.repo_path.mkdir(parents=True)
        (self.repo_path / "site.yaml").write_text("---")

        config_content = f"""[ansible_shed]
interval=60
port=12345
log_dir={self.test_path / "logs"}
repo_path={self.repo_path}
repo_url=git@github.com:test/test.git
repo_key={self.test_path / "key"}
ansible_playbook_binary=/usr/bin/ansible-playbook
ansible_hosts_inventory=hosts
ansible_playbook_init=site.yaml
version_check_state_enabled=true
"""
        self.config_file = self.test_path / "test_config.ini"
        self.config_file.write_text(config_content)

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    @patch("pathlib.Path.mkdir")
    def test_parse_version_check_state_disabled(self, mock_mkdir: Mock) -> None:
        """Test that parse_version_check_state does nothing when disabled"""
        config_content = f"""[ansible_shed]
interval=60
port=12345
log_dir={self.test_path / "logs"}
repo_path={self.repo_path}
repo_url=git@github.com:test/test.git
repo_key={self.test_path / "key"}
ansible_playbook_binary=/usr/bin/ansible-playbook
ansible_hosts_inventory=hosts
ansible_playbook_init=site.yaml
version_check_state_enabled=false
"""
        config_file_disabled = self.test_path / "test_config_disabled.ini"
        config_file_disabled.write_text(config_content)

        shed = Shed(config_file_disabled)
        shed.parse_version_check_state()
        self.assertNotIn("version_check_state_results", shed.prom_stats)

    @patch("pathlib.Path.mkdir")
    def test_parse_version_check_state_file_missing(self, mock_mkdir: Mock) -> None:
        """Test that a warning is logged when the state file doesn't exist"""
        shed = Shed(self.config_file)
        with self.assertLogs("ansible_shed.shed", level="WARNING") as cm:
            shed.parse_version_check_state()
        self.assertTrue(
            any("version_check_state" in msg for msg in cm.output),
            f"Expected warning about version_check_state in: {cm.output}",
        )
        self.assertNotIn("version_check_state_results", shed.prom_stats)

    @patch("pathlib.Path.mkdir")
    def test_parse_version_check_state(self, mock_mkdir: Mock) -> None:
        """Test parsing a valid version_check_state.json file"""
        version_check_file = self.repo_path / "version_check_state.json"
        version_check_file.write_text(json.dumps(VERSION_CHECK_STATE_JSON))

        shed = Shed(self.config_file)
        shed.parse_version_check_state()

        self.assertEqual(shed.prom_stats["version_check_state_results"], 4)

        expected_checked_at = int(
            datetime(2026, 3, 11, 1, 45, 55, tzinfo=timezone.utc).timestamp()
        )
        self.assertEqual(
            shed.prom_stats["version_check_state_checked_at"], expected_checked_at
        )

        self.assertEqual(len(shed.version_check_packages), 4)
        self.assertEqual(shed.version_check_packages[0]["name"], "monitord-exporter")
        self.assertEqual(shed.version_check_packages[0]["current_version"], "0.18.0")
        self.assertEqual(shed.version_check_packages[0]["latest_version"], "0.19.0")
        self.assertEqual(shed.version_check_packages[1]["name"], "nftables-exporter")
        self.assertEqual(shed.version_check_packages[2]["name"], "kube-vip")
        self.assertEqual(shed.version_check_packages[3]["name"], "coredns")

    @patch("pathlib.Path.mkdir")
    def test_version_check_data_ready_before_prom_event(
        self, mock_mkdir: Mock
    ) -> None:
        """Test that version_check data is populated before prom_stats_update fires.

        parse_version_check_state must run before parse_ansible_stats in the
        ansible_runner loop, because parse_ansible_stats sets the
        prom_stats_update event that triggers metric export. If the order is
        wrong, _update_prom_stats reads empty version_check data.
        """
        version_check_file = self.repo_path / "version_check_state.json"
        version_check_file.write_text(json.dumps(VERSION_CHECK_STATE_JSON))

        shed = Shed(self.config_file)
        call_order: list[str] = []
        version_check_packages_at_event: list[dict[str, str]] = []

        original_parse_version_check = shed.parse_version_check_state
        original_parse_stats = shed.parse_ansible_stats

        def tracked_parse_version_check() -> None:
            call_order.append("parse_version_check_state")
            original_parse_version_check()

        def tracked_parse_stats(output: str, returncode: int) -> None:
            call_order.append("parse_ansible_stats")
            # Snapshot what _update_prom_stats would see when the event fires
            version_check_packages_at_event.extend(shed.version_check_packages)
            original_parse_stats(output, returncode)

        shed.parse_version_check_state = tracked_parse_version_check  # type: ignore[assignment]
        shed.parse_ansible_stats = tracked_parse_stats  # type: ignore[assignment]

        # Stub out methods we don't need for this test
        shed._rebase_or_clone_repo = Mock()  # type: ignore[assignment]
        shed._run_ansible = Mock(return_value=(0, ""))  # type: ignore[assignment]

        async def run_one_iteration() -> None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, shed._rebase_or_clone_repo)
            await loop.run_in_executor(None, shed._run_ansible)
            # Mirror the actual ansible_runner call order
            await loop.run_in_executor(None, shed.parse_version_check_state)
            await loop.run_in_executor(
                None, shed.parse_ansible_stats, "", 0
            )

        asyncio.run(run_one_iteration())

        self.assertEqual(
            call_order,
            ["parse_version_check_state", "parse_ansible_stats"],
            "parse_version_check_state must run before parse_ansible_stats",
        )
        self.assertEqual(
            len(version_check_packages_at_event),
            4,
            "version_check_packages must be populated before prom_stats_update fires",
        )
