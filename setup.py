#!/usr/bin/env python3

from setuptools import setup


ptr_params = {
    "entry_point_module": "ansible_shed/main",
    "test_suite": "ansible_shed.tests.base",
    "test_suite_timeout": 300,
    # New coverage can have `exit` in output and break ptr
    # https://github.com/facebookincubator/ptr/issues/107
    #    "required_coverage": {
    #        "ansible_shed/main.py": 50,
    #    },
    "run_flake8": True,
    "run_black": True,
    "run_mypy": True,
}


setup(
    name="ansible_shed",
    version="2021.3.15",
    description=(
        "asyncio ansible tower like shed to run playbooks and have prometheus "
        + "collector stats"
    ),
    packages=["ansible_shed", "ansible_shed.tests"],
    url="http://github.com/cooperlees/ansible_shed/",
    author="Cooper Lees",
    author_email="me@cooperlees.com",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Development Status :: 3 - Alpha",
    ],
    entry_points={"console_scripts": ["ansible-shed = ansible_shed.main:main"]},
    install_requires=["aioprometheus[aiohttp]", "click", "GitPython"],
    extras_require={
        # If you'd like the ansible toolset dependency installed
        "ansible": ["ansible"],
    },
    test_require=["ptr"],
    python_requires=">=3.8",
    test_suite=ptr_params["test_suite"],
)
