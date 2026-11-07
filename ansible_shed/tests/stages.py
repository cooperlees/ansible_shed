#!/usr/bin/env python3

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from aioprometheus.collectors import Gauge, Registry

from ansible_shed.shed import AnsibleJob, parse_ansible_stages, Shed

BASE_CONFIG = """[ansible_shed]
interval=60
port=12345
api_token=change-me-random-token
repo_path={repo}
repo_url=git@github.com:cooperlees/clc_ansible.git
ansible_playbook_binary=/nonexistent/ansible-playbook
ansible_hosts_inventory=hosts
ansible_playbook_init=site.yaml
ansible_skip_tags=zfs
"""

RECAP_HOME1 = """PLAY RECAP *********************************************************************
home1.cooperlees.com       : ok=10   changed=1    unreachable=0    failed=0    skipped=2    rescued=0    ignored=0
"""
RECAP_POST = """PLAY RECAP *********************************************************************
home1.cooperlees.com       : ok=2    changed=0    unreachable=0    failed=0    skipped=1    rescued=0    ignored=0
us.cooperlees.com          : ok=1    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
node-0.cooperlees.com      : ok=3    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0
"""


def _shed_with(extra: str, tmp: str) -> Shed:
    config_path = Path(tmp) / "shed.ini"
    config_path.write_text(BASE_CONFIG.format(repo=tmp) + extra)
    return Shed(config_path)


class ParseAnsibleStagesTests(unittest.TestCase):
    def test_stages_and_parallel_jobs(self) -> None:
        stages = parse_ansible_stages(
            "main.yaml@home1.cooperlees.com, main.yaml@k8s ; post.yaml"
        )
        self.assertEqual(
            stages,
            [
                [
                    AnsibleJob(0, "main.yaml", "home1.cooperlees.com"),
                    AnsibleJob(0, "main.yaml", "k8s"),
                ],
                [AnsibleJob(1, "post.yaml", None)],
            ],
        )

    def test_multiline_and_blank_entries(self) -> None:
        raw = "\nmain.yaml@home1:home2,\n  main.yaml@us,\n;\n;\npost.yaml\n"
        stages = parse_ansible_stages(raw)
        self.assertEqual(len(stages), 2)
        self.assertEqual(stages[0][0].limit, "home1:home2")
        self.assertEqual(stages[1], [AnsibleJob(1, "post.yaml", None)])

    def test_invalid_jobs(self) -> None:
        for raw in ("@home1", "main.yaml@", "main.yaml@  "):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_ansible_stages(raw)

    def test_job_name_and_labels(self) -> None:
        job = AnsibleJob(2, "main.yaml", "k8s")
        self.assertEqual(job.name, "main.yaml@k8s")
        self.assertEqual(
            job.labels, {"stage": "2", "playbook": "main.yaml", "limit": "k8s"}
        )
        self.assertEqual(AnsibleJob(0, "post.yaml", None).name, "post.yaml")
        self.assertNotEqual(job, "main.yaml@k8s")
        self.assertEqual(hash(job), hash(AnsibleJob(2, "main.yaml", "k8s")))
        self.assertIn("main.yaml", repr(job))


class StagedRunTests(unittest.TestCase):
    def test_config_loads_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shed = _shed_with("ansible_stages=a.yaml@x, a.yaml@y; b.yaml\n", tmp)
            self.assertEqual([len(s) for s in shed.ansible_stages], [2, 1])

    def test_invalid_config_falls_back_to_single_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shed = _shed_with("ansible_stages=main.yaml@\n", tmp)
            self.assertEqual(shed.ansible_stages, [])

    def test_build_cmd_uses_job_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shed = _shed_with("", tmp)
            cmd = shed._build_ansible_cmd("main.yaml", "k8s")
            self.assertEqual(cmd[3], "main.yaml")
            self.assertEqual(cmd[cmd.index("--limit") + 1], "k8s")
            self.assertEqual(cmd[cmd.index("--skip-tags") + 1], "zfs")
            self.assertNotIn("--limit", shed._build_ansible_cmd("post.yaml", None))

    def test_single_run_without_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shed = _shed_with("ansible_limit=home1\n", tmp)
            with patch.object(
                shed, "_run_ansible_cmd", return_value=(0, "out")
            ) as run_cmd:
                self.assertEqual(shed._run_ansible(), (0, "out"))
            cmd = run_cmd.call_args.args[0]
            self.assertEqual(cmd[3], "site.yaml")
            self.assertEqual(cmd[cmd.index("--limit") + 1], "home1")
            self.assertEqual(shed.job_stats, [])

    def test_stages_run_in_order_with_parallel_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shed = _shed_with(
                f"log_dir={tmp}/logs\n"
                "ansible_stages=main.yaml@home1, main.yaml@us; post.yaml\n",
                tmp,
            )
            # Both stage-0 jobs must be in flight together, and post.yaml may
            # only start once both have finished.
            barrier = threading.Barrier(2, timeout=5)
            finished: list[str] = []
            lock = threading.Lock()

            def fake_run(cmd: list[str], log_path: Path | None) -> tuple[int, str]:
                playbook = cmd[3]
                limit = cmd[cmd.index("--limit") + 1] if "--limit" in cmd else ""
                if playbook == "main.yaml":
                    barrier.wait()
                else:
                    with lock:
                        self.assertEqual(sorted(finished), ["home1", "us"])
                assert log_path is not None
                self.assertIn("_s", log_path.name)
                with lock:
                    finished.append(limit or playbook)
                if limit == "us":
                    return 2, "us failed\n"
                if limit == "home1":
                    return 0, RECAP_HOME1
                return 4, RECAP_POST

            with patch.object(shed, "_run_ansible_cmd", side_effect=fake_run):
                returncode, output = shed._run_ansible()

            # First non-zero returncode in stage/job order wins.
            self.assertEqual(returncode, 2)
            self.assertIn("===== ansible_shed job main.yaml@us stage=0 rc=2", output)
            self.assertIn("===== ansible_shed job post.yaml stage=1 rc=4", output)
            self.assertEqual(
                [(labels["limit"], rc) for labels, rc, _ in shed.job_stats],
                [("home1", 0), ("us", 2), ("", 4)],
            )
            latest = Path(tmp) / "logs" / "latest.log"
            self.assertEqual(latest.resolve().read_text(), output)

    def test_stages_without_log_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shed = _shed_with("ansible_stages=main.yaml@home1\n", tmp)
            shed.log_dir_path = None
            with patch.object(
                shed, "_run_ansible_cmd", return_value=(0, "ok")
            ) as run_cmd:
                self.assertEqual(shed._run_ansible()[0], 0)
            self.assertIsNone(run_cmd.call_args.args[1])

    @patch("ansible_shed.shed.time")
    def test_host_stats_sum_across_jobs(self, mock_time: Mock) -> None:
        mock_time.return_value = 69
        with tempfile.TemporaryDirectory() as tmp:
            shed = _shed_with("", tmp)
            shed.parse_ansible_stats(RECAP_HOME1 + RECAP_POST, 0)
            self.assertEqual(shed.prom_stats["host_home1.cooperlees.com_ok"], 12)
            self.assertEqual(shed.prom_stats["host_home1.cooperlees.com_skipped"], 3)
            self.assertEqual(shed.prom_stats["host_us.cooperlees.com_ok"], 1)
            # Hyphenated hostnames used to be truncated to "0.cooperlees.com".
            self.assertEqual(shed.prom_stats["host_node-0.cooperlees.com_ok"], 3)
            self.assertNotIn("host_0.cooperlees.com_ok", shed.prom_stats)

    def test_refresh_job_gauges_drops_stale_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shed = _shed_with("", tmp)
            registry = Registry()
            runtime = Gauge("t_job_runtime", "t", registry=registry)
            rcode = Gauge("t_job_rc", "t", registry=registry)
            old = AnsibleJob(0, "site.yaml", None).labels
            new = AnsibleJob(0, "main.yaml", "k8s").labels
            shed.job_stats = [(old, 0, 10)]
            prev = shed._refresh_job_gauges(runtime, rcode, [])
            shed.job_stats = [(new, 1, 20)]
            prev = shed._refresh_job_gauges(runtime, rcode, prev)
            self.assertEqual(prev, [new])
            self.assertEqual(runtime.get(new), 20)
            self.assertEqual(rcode.get(new), 1)
            self.assertNotIn(old, list(runtime.values.keys()))
