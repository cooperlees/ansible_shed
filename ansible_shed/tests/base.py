#!/usr/bin/env python3

import unittest

from click.testing import CliRunner

from ansible_shed.main import main
from ansible_shed.tests.ansible_output import AnsibleOutputTests  # noqa: F401
from ansible_shed.tests.api import APITests  # noqa: F401
from ansible_shed.tests.client_cli import ClientConfigAndCLITests  # noqa: F401
from ansible_shed.tests.client_http import ClientHttpTests  # noqa: F401
from ansible_shed.tests.version_check_state import VersionCheckStateTests  # noqa: F401


class TestCLI(unittest.TestCase):
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
