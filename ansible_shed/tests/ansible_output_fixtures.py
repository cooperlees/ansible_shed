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

# Profile parser always writes these four keys (even for output that lacks
# the profile_tasks/timer callbacks), so they appear with zero values when
# the recap blocks aren't present.
_PROFILE_ZERO_STATS = {
    "ansible_task_count_total": 0,
    "ansible_warnings_count": 0,
    "ansible_deprecation_warnings_count": 0,
    "ansible_profile_tasks_detected": 0,
}

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
    **_PROFILE_ZERO_STATS,
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
    **_PROFILE_ZERO_STATS,
}


# Realistic ansible-playbook output with profile_tasks + timer callbacks
# enabled: 7 TASK headers, PLAY RECAP, TASKS RECAP with 5 rows spanning 4
# roles, PLAYBOOK RECAP, and one of each kind of trailing warning.
ANSIBLE_PROFILE_OUTPUT = """\
PLAY [Common Playbooks] ********************************************************

TASK [Gathering Facts] *********************************************************
ok: [host1.example.com]

TASK [networkd : Make networkd.conf.d dir] *************************************
ok: [host1.example.com]

TASK [networkd : Copy forwarding networkd.conf] ********************************
ok: [host1.example.com]

TASK [networkd : Remove netplan.io] ********************************************
ok: [host1.example.com]

TASK [users : Make user] *******************************************************
ok: [host1.example.com]

TASK [users : Copy ssh keys] ***************************************************
ok: [host1.example.com]

TASK [systemd_oomd : Protect critical services from oomd] **********************
ok: [host1.example.com]

PLAY RECAP *********************************************************************
host1.example.com          : ok=10   changed=2    unreachable=0    failed=0    skipped=3    rescued=0    ignored=0

TASKS RECAP ********************************************************************
===============================================================================
ansible_shed : Install latest ansible_shed ----------------------------- 29.80s
systemd_oomd : Protect critical services from oomd --------------------- 29.38s
networkd : Make networkd.conf.d dir ------------------------------------ 10.50s
users : Copy ssh keys -------------------------------------------------- 8.20s
networkd : Remove netplan.io ------------------------------------------- 5.10s

PLAYBOOK RECAP *****************************************************************
Playbook run took 0 days, 0 hours, 5 minutes, 30 seconds

[WARNING]: kubernetes is not supported.
[DEPRECATION WARNING]: Importing 'to_native' is deprecated.
"""

EXPECTED_PROFILE_TASKS = [
    {"role": "ansible_shed", "task": "Install latest ansible_shed", "seconds": 29.80},
    {
        "role": "systemd_oomd",
        "task": "Protect critical services from oomd",
        "seconds": 29.38,
    },
    {"role": "networkd", "task": "Make networkd.conf.d dir", "seconds": 10.50},
    {"role": "users", "task": "Copy ssh keys", "seconds": 8.20},
    {"role": "networkd", "task": "Remove netplan.io", "seconds": 5.10},
]
EXPECTED_PROFILE_ROLES = {
    "ansible_shed": 29.80,
    "systemd_oomd": 29.38,
    "networkd": 15.60,
    "users": 8.20,
}


# Equal split: 2 tasks per role, 2 roles.
ROLE_AGGREGATION_OUTPUT = """\
TASKS RECAP ********************************************************************
===============================================================================
alpha : task one ------------------------------------------------------- 5.00s
beta : task two -------------------------------------------------------- 4.00s
alpha : task three ----------------------------------------------------- 3.00s
beta : task four ------------------------------------------------------- 2.00s

PLAYBOOK RECAP *****************************************************************
"""


# Recap row with no "<role> : " prefix.
NO_ROLE_PREFIX_RECAP = """\
TASKS RECAP ********************************************************************
===============================================================================
Gathering Facts -------------------------------------------------------- 1.23s

PLAYBOOK RECAP *****************************************************************
"""


# Recap with one valid row and one garbage row that should be skipped.
MALFORMED_RECAP = """\
TASKS RECAP ********************************************************************
===============================================================================
good_role : real task -------------------------------------------------- 7.50s
---- broken ----

PLAYBOOK RECAP *****************************************************************
"""


# Three [WARNING]: and two [DEPRECATION WARNING]: lines should be counted
# exclusively (no double counting).
WARNINGS_FIXTURE = """\
PLAY RECAP *********************************************************************
host1.example.com          : ok=1    changed=0    unreachable=0    failed=0    skipped=0    rescued=0    ignored=0

[WARNING]: first warning.
[WARNING]: second warning.
[DEPRECATION WARNING]: first deprecation.
[WARNING]: third warning.
[DEPRECATION WARNING]: second deprecation.
"""


# TASK headers but no TASKS RECAP block (mid-run failure).
TASK_HEADERS_NO_RECAP = """\
TASK [Gathering Facts] *********************************************************
ok: [host1.example.com]

TASK [role_a : do thing] *******************************************************
ok: [host1.example.com]

TASK [role_b : do other thing] *************************************************
ok: [host1.example.com]
"""
