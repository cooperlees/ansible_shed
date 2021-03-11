#!/usr/bin/env python3

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ansible_shed.shed import Shed
from ansible_shed.tests.ansible_output_fixtures import (
    ANSIBLE_FAIL_CP,
    ANSIBLE_SUCCESS_CP,
    EXPECTED_FAIL_STATS,
    EXPECTED_SUCCESS_STATS,
)


SHED_CONFIG_PATH = Path(__file__).parent.parent.parent / "ansible_shed.ini"


class AnsibleOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shed = Shed(SHED_CONFIG_PATH)
        return super().setUp()

    @patch("ansible_shed.shed.time")
    def test_parsing_ansible_output(self, mock_time: Mock) -> None:
        mock_time.return_value = 69
        self.shed.parse_ansible_stats(ANSIBLE_SUCCESS_CP)
        self.assertEqual(self.shed.prom_stats, EXPECTED_SUCCESS_STATS)
        # Run fail stats to ensure clearing works
        self.shed.parse_ansible_stats(ANSIBLE_FAIL_CP)
        self.assertEqual(self.shed.prom_stats, EXPECTED_FAIL_STATS)
