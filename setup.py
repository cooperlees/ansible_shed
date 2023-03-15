#!/usr/bin/env python3

from os import environ

from setuptools import setup


ptr_params = {
    "entry_point_module": "ansible_shed/main",
    "test_suite": "ansible_shed.tests.base",
    "test_suite_timeout": 300,
    "required_coverage": {
        "ansible_shed/main.py": 49,
        "ansible_shed/shed.py": 40,
    },
    "run_black": True,
    "run_flake8": True,
    "run_mypy": True,
    "run_usort": True,
}


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
        verbose=True,
    )


setup(
    name="ansible_shed",
    version="2023.3.15",
    description=(
        "asyncio ansible tower like shed to run playbooks and have prometheus "
        + "collector stats"
    ),
    packages=["ansible_shed", "ansible_shed.tests"],
    ext_modules=ext_modules,
    url="http://github.com/cooperlees/ansible_shed/",
    author="Cooper Lees",
    author_email="me@cooperlees.com",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Development Status :: 3 - Alpha",
    ],
    entry_points={"console_scripts": ["ansible-shed = ansible_shed.main:main"]},
    install_requires=["aioprometheus[aiohttp]", "click", "GitPython"],
    extras_require={
        # If you'd like the ansible toolset dependency installed
        "ansible": ["ansible"],
    },
    test_require=["ptr"],
    python_requires=">=3.10",
    test_suite=ptr_params["test_suite"],
)
