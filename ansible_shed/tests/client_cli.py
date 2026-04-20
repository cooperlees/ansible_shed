#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from ansible_shed.cli.main import main as cli_main
from ansible_shed.client.config import load_api_config


class ClientConfigAndCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_path = Path(self.test_dir.name)
        self.config_file = self.test_path / "test_config.ini"
        self.config_file.write_text("""[ansible_shed]
port=12345
api_token=test-token
""")

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    def test_load_api_config(self) -> None:
        loaded = load_api_config(self.config_file)
        self.assertEqual(loaded.base_url, "http://127.0.0.1:12345")
        self.assertEqual(loaded.api_token, "test-token")

    def test_load_api_config_raises_on_default_token(self) -> None:
        self.config_file.write_text("""[ansible_shed]
port=12345
api_token=change-me-random-token
""")
        with self.assertRaisesRegex(ValueError, "api_token is not configured"):
            load_api_config(self.config_file)

    @patch("ansible_shed.cli.main._run_command", new_callable=AsyncMock)
    def test_cli_force_run_invokes_async_runner(
        self, mock_run_command: AsyncMock
    ) -> None:
        mock_run_command.return_value = {"status": "scheduled"}
        runner = CliRunner()
        result = runner.invoke(
            cli_main,
            ["--config", str(self.config_file), "force-run"],
        )
        self.assertEqual(result.exit_code, 0)
        mock_run_command.assert_awaited_once()
