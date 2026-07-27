#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ansible_shed.shed import Shed


class RebaseOrCloneRepoTests(unittest.TestCase):
    """Regression tests for the leaked `git cat-file --batch-check` bug.

    `Repo(...)` must always be used as a context manager (or otherwise
    explicitly `.close()`-d): GitPython lazily starts a persistent
    `git cat-file --batch-check` helper process per `Repo` instance and never
    tears it down on its own. `_rebase_or_clone_repo` builds a fresh `Repo`
    every run_interval_seconds forever, so an unclosed one leaks one such
    process per cycle - enough of these accumulating eventually wedges a
    later fetch/checkout indefinitely, with no exception and no crash.
    """

    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_path = Path(self.test_dir.name)
        self.repo_path = self.test_path / "repo"
        self.config_file = self.test_path / "test_config.ini"
        self.config_file.write_text(f"""[ansible_shed]
interval=60
port=12345
repo_path={self.repo_path}
repo_url=git@github.com:test/test.git
repo_key={self.test_path / "key"}
ansible_hosts_inventory=hosts
ansible_playbook_init=site.yaml
""")

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    @patch("ansible_shed.shed.Repo")
    def test_fetch_and_checkout_path_closes_repo(
        self, mock_repo_cls: MagicMock
    ) -> None:
        self.repo_path.mkdir(parents=True)
        (self.repo_path / "site.yaml").write_text("---")
        shed = Shed(self.config_file)

        mock_repo = mock_repo_cls.return_value
        mock_repo.__enter__.return_value = mock_repo

        shed._rebase_or_clone_repo()

        mock_repo_cls.assert_called_once_with(self.repo_path)
        mock_repo.__enter__.assert_called_once()
        mock_repo.__exit__.assert_called_once()
        mock_repo.remotes.origin.fetch.assert_called_once()
        mock_repo.remotes.origin.refs.main.checkout.assert_called_once()

    @patch("ansible_shed.shed.Repo")
    def test_clone_path_closes_repo(self, mock_repo_cls: MagicMock) -> None:
        # repo_path doesn't exist and site.yaml (init_file) doesn't either,
        # so this takes the clone_from(...) branch instead.
        shed = Shed(self.config_file)

        mock_repo = mock_repo_cls.clone_from.return_value
        mock_repo.__enter__.return_value = mock_repo

        shed._rebase_or_clone_repo()

        mock_repo_cls.clone_from.assert_called_once()
        mock_repo.__enter__.assert_called_once()
        mock_repo.__exit__.assert_called_once()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
