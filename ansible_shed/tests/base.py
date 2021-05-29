#!/usr/bin/env python3

import unittest

from ansible_shed.main import main
from ansible_shed.tests.ansible_output import AnsibleOutputTests  # noqa: F401
from click.testing import CliRunner


class TestCLI(unittest.TestCase):
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
