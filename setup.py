#!/usr/bin/env python3

from os import environ

from setuptools import setup

ext_modules = []
if "MYPYC_BUILD" in environ:
    print("mypyc build time ...")
    from mypyc.build import mypycify

    ext_modules = mypycify(
        [
            "ansible_shed/__init__.py",
            "ansible_shed/main.py",
            "ansible_shed/shed.py",
        ],
        opt_level="3",
        verbose=True,
    )

setup(ext_modules=ext_modules)
