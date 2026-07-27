#!/usr/bin/env python3

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from git import Repo

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


class RealRepoIntegrationTests(unittest.TestCase):
    """Exercises _rebase_or_clone_repo against a real local git repo with
    `git.Repo` completely unmocked.

    The tests above mock `ansible_shed.shed.Repo` out entirely, so they only
    prove our code *calls* `__enter__`/`__exit__` - they can't tell us
    whether the real GitPython `Repo` class actually supports being used as a
    context manager. This proves that concretely: if it didn't, this test
    would raise `TypeError: 'Repo' object does not support the context
    manager protocol` the moment `_rebase_or_clone_repo` ran.
    """

    def setUp(self) -> None:
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_path = Path(self.test_dir.name)
        self.remote_path = self.test_path / "remote"
        self.repo_path = self.test_path / "repo"

        self.remote_path.mkdir(parents=True)
        self._git("init", "-q", "-b", "main")
        (self.remote_path / "site.yaml").write_text("---\n# v1\n")
        self._git("add", "site.yaml")
        self._commit("first")

        self.config_file = self.test_path / "test_config.ini"
        self.config_file.write_text(f"""[ansible_shed]
interval=60
port=12345
repo_path={self.repo_path}
repo_url={self.remote_path}
repo_key={self.test_path / "unused_key"}
ansible_hosts_inventory=hosts
ansible_playbook_init=site.yaml
""")

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.remote_path, check=True)

    def _commit(self, message: str) -> None:
        self._git(
            "-c",
            "user.email=t@t.com",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            message,
        )

    def _remote_head(self) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.remote_path,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def test_clone_then_fetch_and_checkout_against_real_repo(self) -> None:
        shed = Shed(self.config_file)

        # repo_path doesn't exist yet -> takes the clone_from(...) path.
        shed._rebase_or_clone_repo()

        self.assertTrue((self.repo_path / "site.yaml").exists())
        with Repo(self.repo_path) as cloned:
            self.assertEqual(cloned.head.commit.hexsha, self._remote_head())

        # Add a second commit on the "remote" then rerun -> now init_file
        # (site.yaml) exists in repo_path, so this takes the real
        # fetch + checkout path instead.
        (self.remote_path / "site.yaml").write_text("---\n# v2\n")
        self._git("add", "site.yaml")
        self._commit("second")

        shed._rebase_or_clone_repo()

        with Repo(self.repo_path) as updated:
            self.assertEqual(updated.head.commit.hexsha, self._remote_head())
        self.assertEqual((self.repo_path / "site.yaml").read_text(), "---\n# v2\n")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
