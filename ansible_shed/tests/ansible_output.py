#!/usr/bin/env python3

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ansible_shed.shed import Shed
from ansible_shed.tests.ansible_output_fixtures import (
    ANSIBLE_FAIL_OUTPUT,
    ANSIBLE_PROFILE_OUTPUT,
    ANSIBLE_SUCCESS_OUTPUT,
    EXPECTED_FAIL_STATS,
    EXPECTED_PROFILE_ROLES,
    EXPECTED_PROFILE_TASKS,
    EXPECTED_SUCCESS_STATS,
    MALFORMED_RECAP,
    NO_ROLE_PREFIX_RECAP,
    ROLE_AGGREGATION_OUTPUT,
    TASK_HEADERS_NO_RECAP,
    WARNINGS_FIXTURE,
)

SHED_CONFIG_PATH = Path(__file__).parent.parent.parent / "ansible_shed.ini"


class AnsibleOutputTests(unittest.TestCase):
    @patch("pathlib.Path.mkdir")
    def setUp(self, mock_mkdir: Mock) -> None:
        self.shed = Shed(SHED_CONFIG_PATH)
        return super().setUp()

    @patch("ansible_shed.shed.time")
    def test_parsing_ansible_output(self, mock_time: Mock) -> None:
        mock_time.return_value = 69
        self.shed.parse_ansible_stats(ANSIBLE_SUCCESS_OUTPUT, 0)
        self.assertEqual(self.shed.prom_stats, EXPECTED_SUCCESS_STATS)
        # Run fail stats to ensure clearing works
        self.shed.parse_ansible_stats(ANSIBLE_FAIL_OUTPUT, 1)
        self.assertEqual(self.shed.prom_stats, EXPECTED_FAIL_STATS)


class AnsibleProfileTests(unittest.TestCase):
    @patch("pathlib.Path.mkdir")
    def setUp(self, mock_mkdir: Mock) -> None:
        self.shed = Shed(SHED_CONFIG_PATH)
        return super().setUp()

    def test_parse_profile_full(self) -> None:
        self.shed.parse_ansible_profile(ANSIBLE_PROFILE_OUTPUT)

        self.assertEqual(self.shed.prom_stats["ansible_profile_tasks_detected"], 1)
        self.assertEqual(self.shed.prom_stats["ansible_task_count_total"], 7)
        self.assertEqual(self.shed.prom_stats["ansible_warnings_count"], 1)
        self.assertEqual(self.shed.prom_stats["ansible_deprecation_warnings_count"], 1)

        self.assertEqual(self.shed.profile_task_runtimes, EXPECTED_PROFILE_TASKS)
        # Per-role aggregate sums match (float comparison with tolerance).
        self.assertEqual(
            set(self.shed.profile_role_runtimes.keys()),
            set(EXPECTED_PROFILE_ROLES.keys()),
        )
        for role, expected_total in EXPECTED_PROFILE_ROLES.items():
            self.assertAlmostEqual(
                self.shed.profile_role_runtimes[role], expected_total, places=4
            )

    def test_parse_profile_top_n_truncation(self) -> None:
        self.shed.profile_tasks_top_n = 2
        self.shed.parse_ansible_profile(ANSIBLE_PROFILE_OUTPUT)

        self.assertEqual(len(self.shed.profile_task_runtimes), 2)
        # The top-2 by descending duration are the ansible_shed and
        # systemd_oomd tasks (29.80s and 29.38s).
        self.assertEqual(self.shed.profile_task_runtimes[0]["role"], "ansible_shed")
        self.assertEqual(self.shed.profile_task_runtimes[1]["role"], "systemd_oomd")
        # Role aggregates are the sum across the truncated top-2 only.
        self.assertEqual(
            self.shed.profile_role_runtimes,
            {"ansible_shed": 29.80, "systemd_oomd": 29.38},
        )

    def test_parse_profile_absent(self) -> None:
        # ANSIBLE_SUCCESS_OUTPUT has no TASKS RECAP and no TASK headers.
        self.shed.parse_ansible_profile(ANSIBLE_SUCCESS_OUTPUT)

        self.assertEqual(self.shed.prom_stats["ansible_profile_tasks_detected"], 0)
        self.assertEqual(self.shed.prom_stats["ansible_task_count_total"], 0)
        self.assertEqual(self.shed.profile_task_runtimes, [])
        self.assertEqual(self.shed.profile_role_runtimes, {})

    def test_parse_profile_role_aggregation(self) -> None:
        self.shed.parse_ansible_profile(ROLE_AGGREGATION_OUTPUT)

        self.assertAlmostEqual(self.shed.profile_role_runtimes["alpha"], 8.0, places=4)
        self.assertAlmostEqual(self.shed.profile_role_runtimes["beta"], 6.0, places=4)

    def test_parse_profile_no_role_prefix(self) -> None:
        self.shed.parse_ansible_profile(NO_ROLE_PREFIX_RECAP)

        self.assertEqual(len(self.shed.profile_task_runtimes), 1)
        entry = self.shed.profile_task_runtimes[0]
        self.assertEqual(entry["role"], "")
        self.assertEqual(entry["task"], "Gathering Facts")
        self.assertAlmostEqual(float(entry["seconds"]), 1.23, places=4)
        # Role aggregate keys correctly under empty string.
        self.assertEqual(set(self.shed.profile_role_runtimes.keys()), {""})

    def test_parse_profile_warnings_count_exclusive(self) -> None:
        self.shed.parse_ansible_profile(WARNINGS_FIXTURE)

        self.assertEqual(self.shed.prom_stats["ansible_warnings_count"], 3)
        self.assertEqual(self.shed.prom_stats["ansible_deprecation_warnings_count"], 2)

    def test_parse_profile_malformed_row_skipped(self) -> None:
        self.shed.parse_ansible_profile(MALFORMED_RECAP)

        # Garbage row dropped; good row preserved.
        self.assertEqual(len(self.shed.profile_task_runtimes), 1)
        entry = self.shed.profile_task_runtimes[0]
        self.assertEqual(entry["role"], "good_role")
        self.assertEqual(entry["task"], "real task")
        self.assertAlmostEqual(float(entry["seconds"]), 7.50, places=4)
        self.assertEqual(self.shed.prom_stats["ansible_profile_tasks_detected"], 1)

    def test_parse_profile_task_count_only(self) -> None:
        self.shed.parse_ansible_profile(TASK_HEADERS_NO_RECAP)

        self.assertEqual(self.shed.prom_stats["ansible_task_count_total"], 3)
        self.assertEqual(self.shed.prom_stats["ansible_profile_tasks_detected"], 0)
        self.assertEqual(self.shed.profile_task_runtimes, [])
        self.assertEqual(self.shed.profile_role_runtimes, {})

    @patch("ansible_shed.shed.time")
    def test_parse_ansible_stats_invokes_profile(self, mock_time: Mock) -> None:
        # ANSIBLE_PROFILE_OUTPUT has both PLAY RECAP and TASKS RECAP.
        mock_time.return_value = 42
        self.shed.parse_ansible_stats(ANSIBLE_PROFILE_OUTPUT, 0)

        # Per-host stats are populated.
        self.assertEqual(self.shed.prom_stats["host_host1.example.com_ok"], 10)
        self.assertEqual(self.shed.prom_stats["host_host1.example.com_changed"], 2)
        # Profile fields populated in the same pass.
        self.assertEqual(self.shed.prom_stats["ansible_profile_tasks_detected"], 1)
        self.assertEqual(self.shed.prom_stats["ansible_task_count_total"], 7)
        self.assertEqual(len(self.shed.profile_task_runtimes), 5)

    def test_top_n_config_default(self) -> None:
        # ansible_shed.ini does not set profile_tasks_top_n; default is 20.
        self.assertEqual(self.shed.profile_tasks_top_n, 20)
