#!/usr/bin/env python3

from subprocess import CompletedProcess


ANSIBLE_FAIL_CP = CompletedProcess(["ansible-playbook"], 1, "", "")
ANSIBLE_SUCCESS_CP = CompletedProcess(["ansible-playbook"], 0, "", "")
