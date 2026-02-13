#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ansible_shed.shed import Shed


class VaultPassTests(unittest.TestCase):
    def setUp(self) -> None:
        # Create a temporary directory for testing
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_path = Path(self.test_dir.name)

        # Create a temporary config file
        self.config_file = self.test_path / "test_config.ini"
        self.vault_source = self.test_path / "vault_source.txt"
        self.repo_path = self.test_path / "repo"

        # Write test vault password
        self.vault_source.write_text("test_password_123")

        # Create minimal config
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
vault_pass_file={self.vault_source}
"""
        self.config_file.write_text(config_content)

        # Create repo directory
        self.repo_path.mkdir(parents=True)
        (self.repo_path / "site.yaml").write_text("---")

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    @patch("pathlib.Path.mkdir")
    def test_vault_pass_file_read_from_config(self, mock_mkdir: Mock) -> None:
        """Test that vault_pass_file is read from config"""
        shed = Shed(self.config_file)
        self.assertEqual(shed.vault_pass_file, str(self.vault_source))

    @patch("pathlib.Path.mkdir")
    def test_vault_pass_file_not_configured(self, mock_mkdir: Mock) -> None:
        """Test that vault_pass_file is None when not configured"""
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
"""
        config_file_no_vault = self.test_path / "test_config_no_vault.ini"
        config_file_no_vault.write_text(config_content)

        shed = Shed(config_file_no_vault)
        self.assertIsNone(shed.vault_pass_file)

    @patch("pathlib.Path.mkdir")
    def test_setup_vault_pass_copies_file(self, mock_mkdir: Mock) -> None:
        """Test that _setup_vault_pass copies the file correctly"""
        shed = Shed(self.config_file)
        shed._setup_vault_pass()

        vault_dest = self.repo_path / ".vault_pass"
        self.assertTrue(vault_dest.exists())
        self.assertEqual(vault_dest.read_text(), "test_password_123")
        # Check that file has restrictive permissions (owner read/write only)
        self.assertEqual(vault_dest.stat().st_mode & 0o777, 0o600)

    @patch("pathlib.Path.mkdir")
    def test_setup_vault_pass_no_config(self, mock_mkdir: Mock) -> None:
        """Test that _setup_vault_pass handles no vault_pass_file gracefully"""
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
"""
        config_file_no_vault = self.test_path / "test_config_no_vault.ini"
        config_file_no_vault.write_text(config_content)

        shed = Shed(config_file_no_vault)
        # Should not raise an exception
        shed._setup_vault_pass()

        vault_dest = self.repo_path / ".vault_pass"
        self.assertFalse(vault_dest.exists())

    @patch("pathlib.Path.mkdir")
    def test_setup_vault_pass_source_not_exists(self, mock_mkdir: Mock) -> None:
        """Test that _setup_vault_pass handles missing source file gracefully"""
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
vault_pass_file=/nonexistent/vault_file
"""
        config_file_bad_vault = self.test_path / "test_config_bad_vault.ini"
        config_file_bad_vault.write_text(config_content)

        shed = Shed(config_file_bad_vault)
        # Should not raise an exception
        shed._setup_vault_pass()

        vault_dest = self.repo_path / ".vault_pass"
        self.assertFalse(vault_dest.exists())
