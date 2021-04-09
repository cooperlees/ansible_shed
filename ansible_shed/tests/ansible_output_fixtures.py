#!/usr/bin/env python3


ANSIBLE_FAIL_OUTPUT = """\
PLAY RECAP *********************************************************************
unittest1.cooperlees.com       : ok=0    changed=0    unreachable=0    failed=1    skipped=1    rescued=0    ignored=0
unittest2.cooperlees.com       : ok=7    changed=0    unreachable=0    failed=0    skipped=1    rescued=0    ignored=0
"""

ANSIBLE_SUCCESS_OUTPUT = """\
PLAY RECAP *********************************************************************
unittest1.cooperlees.com       : ok=7    changed=0    unreachable=0    failed=0    skipped=1    rescued=0    ignored=0
unittest2.cooperlees.com       : ok=7    changed=0    unreachable=0    failed=0    skipped=1    rescued=0    ignored=0
"""

# ansible keys are only first because we run after SUCCESS parsing ...
EXPECTED_FAIL_STATS = {
    "ansible_last_run_returncode": 1,
    "ansible_stats_last_updated": 69,
    "host_unittest1.cooperlees.com_ok": 0,
    "host_unittest1.cooperlees.com_changed": 0,
    "host_unittest1.cooperlees.com_unreachable": 0,
    "host_unittest1.cooperlees.com_failed": 1,
    "host_unittest1.cooperlees.com_skipped": 1,
    "host_unittest1.cooperlees.com_rescued": 0,
    "host_unittest1.cooperlees.com_ignored": 0,
    "host_unittest2.cooperlees.com_ok": 7,
    "host_unittest2.cooperlees.com_changed": 0,
    "host_unittest2.cooperlees.com_unreachable": 0,
    "host_unittest2.cooperlees.com_failed": 0,
    "host_unittest2.cooperlees.com_skipped": 1,
    "host_unittest2.cooperlees.com_rescued": 0,
    "host_unittest2.cooperlees.com_ignored": 0,
}
EXPECTED_SUCCESS_STATS = {
    "host_unittest1.cooperlees.com_ok": 7,
    "host_unittest1.cooperlees.com_changed": 0,
    "host_unittest1.cooperlees.com_unreachable": 0,
    "host_unittest1.cooperlees.com_failed": 0,
    "host_unittest1.cooperlees.com_skipped": 1,
    "host_unittest1.cooperlees.com_rescued": 0,
    "host_unittest1.cooperlees.com_ignored": 0,
    "host_unittest2.cooperlees.com_ok": 7,
    "host_unittest2.cooperlees.com_changed": 0,
    "host_unittest2.cooperlees.com_unreachable": 0,
    "host_unittest2.cooperlees.com_failed": 0,
    "host_unittest2.cooperlees.com_skipped": 1,
    "host_unittest2.cooperlees.com_rescued": 0,
    "host_unittest2.cooperlees.com_ignored": 0,
    "ansible_last_run_returncode": 0,
    "ansible_stats_last_updated": 69,
}
