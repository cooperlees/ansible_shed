#!/usr/bin/env python3

import unittest
from pathlib import Path

from ansible_shed.main import _load_shed_config
from ansible_shed.shed import Shed
from ansible_shed.tests.ansible_output_fixtures import (  # noqa: F401
    ANSIBLE_FAIL_CP,
    ANSIBLE_SUCCESS_CP,
)


SHED_CONFIG_PATH = Path(__file__).parent.parent / "shed.ini"
SHED_CONFIG = _load_shed_config(SHED_CONFIG_PATH)


class AnsibleOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shed = Shed(SHED_CONFIG)
        return super().setUp()
