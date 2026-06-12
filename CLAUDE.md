# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A long-running asyncio daemon ("Ansible tower in a shed") that, on an interval, git-clones/rebases an Ansible repo, runs `ansible-playbook`, parses the output, and exports the results as Prometheus metrics over HTTP. It also serves a small token-authenticated REST API to pause / force-run / healthcheck.

## Commands

`ptr` (Python Test Runner) is the single entrypoint for CI and local checks. It reads its config from `[tool.ptr]` in `pyproject.toml` and runs the full gate: unittest suite + coverage thresholds + mypy + black + flake8 + usort.

```bash
pip install ptr
ptr                  # run everything CI runs (tests, coverage, mypy, black, flake8, usort)
ptr --print-cov      # also print the coverage report
ptr --keep-venv      # reuse ptr's throwaway venv between runs
```

- `ptr` builds a fresh venv and installs the project each run, so it is the source of truth — if `ptr` passes, CI passes.
- The test suite is a single aggregated module, `ansible_shed.tests.base`, which re-imports every other test class (see `ansible_shed/tests/base.py`). New test classes must be imported there or `ptr` will not run them.
- **Run one test directly** (faster inner loop, needs deps installed in your env):
  ```bash
  python -m unittest ansible_shed.tests.ansible_output.RunAnsibleStderrTests
  python -m unittest ansible_shed.tests.ansible_output.AnsibleProfileTests.test_parse_profile_full
  ```
- Formatting/import order is enforced: run `black ansible_shed/` and `usort format ansible_shed/` before committing. usort sorts ALL-CAPS names after mixed-case (e.g. `from subprocess import PIPE, Popen, run, STDOUT`).

### mypyc compiled build

The code is strict-typed specifically so it can be compiled to C with mypyc. `setup.py` is a thin shim that only adds `mypycify` ext_modules when `MYPYC_BUILD=1` is set; all static metadata lives in `pyproject.toml`. Keep the code mypyc-compatible (it must pass `--strict` mypy).

```bash
MYPYC_BUILD=1 pip install -U pip mypy setuptools wheel && MYPYC_BUILD=1 pip install .
```

## Architecture

Two coroutines are gathered in `main.py:async_main` and run for the life of the process:

1. `Shed.prometheus_server()` — an aiohttp app exposing `GET /metrics` plus the REST API (`POST /pause`, `POST /force-run`, `GET /healthz`).
2. `Shed.ansible_runner()` — the control loop.

Both live on the single `Shed` god-object (`ansible_shed/shed.py`, ~850 lines), which holds all shared state: parsed config, the `prom_stats` dict, pause/force-run state, and an `asyncio.Event` (`prom_stats_update`) used to hand parsed stats from the runner to the metrics exporter.

### The run loop (`ansible_runner`)

Each iteration: **reload config from disk** → check force-run/pause → rebase-or-clone the repo → run ansible → parse version-check state → parse ansible stats (which sets `prom_stats_update`, triggering `_update_prom_stats` to push gauges) → sleep `interval - runtime`. Key consequences:

- The `.ini` is re-read every loop, so config edits take effect on the next run without a restart.
- All blocking work (`git`, `ansible-playbook`, file parsing) is dispatched via `loop.run_in_executor` to keep the event loop responsive for the metrics/API server.
- Pause is a timestamp gate; force-run is an event that can break a pause or a sleep early.

### Output parsing → metrics

`_run_ansible` shells out to `ansible-playbook` and returns `(returncode, combined_output)`. **Ansible emits `[WARNING]` / `[DEPRECATION WARNING]` lines on stderr**, so both stdout and stderr must be folded into the returned string or the parsers undercount — this is a real bug class here. Parsing is split into small helpers (`_count_run_artifacts`, `_extract_recap_rows`, `parse_ansible_profile`, `parse_version_check_state`) that populate `prom_stats` and the profile gauges. Optional features keyed off config:

- `profile_tasks_top_n`: parses the `ansible.posix.profile_tasks` TASKS RECAP block into per-task/per-role runtime gauges (top N by duration).
- `version_check_state_enabled`: reads `version_check_state.json` from the repo root into package-upgrade gauges.

### Ansible virtualenv activation

`ansible_playbook_binary` must point at `<venv>/bin/ansible-playbook`. `_activate_ansible_virtualenv` derives the sibling `<venv>/bin/activate` and activates that environment so ansible's own deps resolve. Pointing the config at a system `ansible-playbook` outside a venv will not work.

### Client / CLI

`ansible-shed-cli` (`ansible_shed/cli/main.py`, a click app) is a thin operator tool for the same REST API. It reuses `api_token` and `port` from the same `.ini` via `ansible_shed/client/config.py`, and `ansible_shed/client/http.py` (`AnsibleShedApiClient`) is the shared aiohttp client. Auth is the `X-API-Token` header; if `api_token` is left at the `change-me-random-token` placeholder, the authenticated endpoints are disabled.

## Releasing

Versioning is CalVer `YYYY.M.D` (the maintainer's local Chicago date, not UTC — so a release tagged `2026.6.11` can be created during `2026-06-12` UTC). The version lives in `pyproject.toml`. Same-day re-releases use a `.postN` suffix (e.g. `2026.5.5.post2`).

Cutting a release (version bumps land directly on `main`):

```bash
# 1. Bump the version in pyproject.toml, then commit + push to main
git add pyproject.toml && git commit -m "Bump version to 2026.6.11" && git push

# 2. Publish a GitHub Release whose tag == the version; this triggers publishing
gh release create 2026.6.11 --target main --title "2026.6.11" --generate-notes

# 3. Watch the publish workflow
gh run list --workflow=release.yml --limit 3
```

The tag push to a published Release triggers `.github/workflows/release.yml`, which:

- builds the sdist + pure-Python fallback wheel, and
- builds mypyc-compiled wheels for cp313/cp314 × x86_64/aarch64 (aarch64 on native `ubuntu-24.04-arm` runners, not QEMU), then
- publishes everything to PyPI via trusted publishing.

The `publish` job has `needs: [sdist, wheels]` and requires every wheel matrix job to succeed, so a single failing arch/python build blocks the entire release (no partial upload). `ci.yml` runs `ptr` on every push/PR but does not publish.
