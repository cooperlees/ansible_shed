# ansible_shed

Simple Ansible tower to run playbooks via `ansible-playbook` + export prometheus metrics about success.

## Example Run + Stats

Playbook(s) will be run on host(s) and then the output parsed to generated statistics

**Log example:**
```console
[2021-03-09 15:59:36,239] DEBUG: Starting /usr/local/bin/ansible-shed (main.py:71)
[2021-03-09 15:59:36,239] DEBUG: Using selector: EpollSelector (selector_events.py:59)
[2021-03-09 15:59:36,241] DEBUG: Prometheus metrics server starting on :::12345/metrics (service.py:133)
[2021-03-09 15:59:36,243] INFO: Rebasing /tmp/ansible_shed/repo from git@github.com:cooperlees/clc_ansible.git (shed.py:36)
[2021-03-09 15:59:36,246] DEBUG: Prometheus metrics server started on http://[::]:12345/metrics (service.py:160)
[2021-03-09 15:59:36,246] INFO: Serving prometheus metrics on: http://[::]:12345/metrics (shed.py:150)
Already up to date.
Current branch master is up to date.
[2021-03-09 15:59:37,480] INFO: Running ansible-playbook: '/home/cooper/venvs/a/bin/ansible-playbook --inventory hosts site.yaml --limit home2.cooperlees.com --tags chrony --skip-tags php_static_files,zfs' (shed.py:70)
[2021-03-09 15:59:38,906] DEBUG: negotiating {'*/*'} resulted in choosing TextFormatter (negotiator.py:32)
[2021-03-09 15:59:38,908] INFO: ::1 [09/Mar/2021:15:59:38 +0000] "GET /metrics HTTP/1.1" 200 1128 "-" "curl/7.68.0" (web_log.py:206)
[2021-03-09 15:59:53,651] INFO: Finished running ansible in 16s (shed.py:75)
[2021-03-09 15:59:53,651] INFO: Parsing ansible run output to update stats (shed.py:79)
[2021-03-09 15:59:53,652] DEBUG: Host Results: home2.cooperlees.com - ok=7    changed=0    unreachable=0    failed=0    skipped=1    rescued=0    ignored=0    (shed.py:92)
[2021-03-09 15:59:53,652] DEBUG: Updating prometheus stats due to event being set (shed.py:129)
[2021-03-09 15:59:53,652] INFO: Updated 10 metrics (shed.py:141)
[2021-03-09 15:59:53,652] INFO: Finished ansible run in 17s. Sleeping for 43s (shed.py:176)
[2021-03-09 15:59:53,652] DEBUG: Stats:
{
  "ansible_last_run_returncode": 0,
  "ansible_last_run_time": 16,
  "ansible_stats_last_updated": 1615305593,
  "host_home2.cooperlees.com_changed": 0,
  "host_home2.cooperlees.com_failed": 0,
  "host_home2.cooperlees.com_ignored": 0,
  "host_home2.cooperlees.com_ok": 7,
  "host_home2.cooperlees.com_rescued": 0,
  "host_home2.cooperlees.com_skipped": 1,
  "host_home2.cooperlees.com_unreachable": 0
} (shed.py:177)
[2021-03-09 15:59:57,045] DEBUG: negotiating {'*/*'} resulted in choosing TextFormatter (negotiator.py:32)
[2021-03-09 15:59:57,047] INFO: ::1 [09/Mar/2021:15:59:57 +0000] "GET /metrics HTTP/1.1" 200 1577 "-" "curl/7.68.0" (web_log.py:206)
```

**Metrics Example:**
```console
# HELP ansible_changed Number of 'changed' plays
# TYPE ansible_changed gauge
ansible_changed{hostname="home2.cooperlees.com"}
# HELP ansible_failed Number of failed plays on hosts
# TYPE ansible_failed gauge
ansible_failed{hostname="home2.cooperlees.com"} 0
# HELP ansible_ignored Number of ignored plays on hosts
# TYPE ansible_ignored gauge
ansible_ignored{hostname="home2.cooperlees.com"} 0
# HELP ansible_last_run_returncode UNIX return code of the ansible-playbook process
# TYPE ansible_last_run_returncode gauge
ansible_last_run_returncode 0
# HELP ansible_last_run_time Time in seconds it took the ansible-playbook process to execute
# TYPE ansible_last_run_time gauge
ansible_last_run_time 17
# HELP ansible_ok Number of 'ok' (no change) plays
# TYPE ansible_ok gauge
ansible_ok{hostname="home2.cooperlees.com"} 7
# HELP ansible_rescued Number of rescued plays on hosts
# TYPE ansible_rescued gauge
ansible_rescued{hostname="home2.cooperlees.com"} 0
# HELP ansible_skipped Number of skipped plays on hosts
# TYPE ansible_skipped gauge
ansible_skipped{hostname="home2.cooperlees.com"} 1
# HELP ansible_stats_last_updated UNIX timestamp of last time we updated the stats
# TYPE ansible_stats_last_updated gauge
ansible_stats_last_updated 1615305655
# HELP ansible_unreachable Number of inaccessible hosts
# TYPE ansible_unreachable gauge
ansible_unreachable{hostname="home2.cooperlees.com"} 0
```

- Avaliable http://IP:PORT/metrics
  - All [aioprometheus](https://github.com/claws/aioprometheus) powered

## Install

We're not on PyPI as I don't feel the need (if we get popular that's easy to fix).

- `pip install git+git://github.com/cooperlees/ansible_shed`

or if you want `ansible` tools installed into the same Python environment use our *ansible* extra install:

- `pip install git+git://github.com/cooperlees/ansible_shed#egg=ansible_shed[ansible]`

### SystemD

Today I only run it by systemd cause it makes SSH auth easier. Would happily take a Dockerfile PR.

- [Example SystemD Unit](ansible_shed.service)

## Config

*(TODO: Full config file docs - PR welcome)*
We have a simple ini file to point @ your `ansbile-playbook` binary and arguments.
If not specified, ansible_shed defaults to look for `/etc/ansible_shed.ini`

Also other things like:

- `interval`: Minutes between `ansible-playbook` runs
- `start_splay`: Upper max of time to wait before first `ansible-playbook` run after starting the service - Code generates a random int from 0 to this upper max.
- `port`: Statistics listening port + interval
