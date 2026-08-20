# android-setup task aliases

set dotenv-load := false

default:
    @just --list

profiles:
    PYTHONPATH=src python3 -m android_setup profiles list

profile-add name from="":
    #!/usr/bin/env sh
    set -eu
    if [ -n "{{ from }}" ]; then
        PYTHONPATH=src python3 -m android_setup profiles add "{{ name }}" --from "{{ from }}"
    else
        PYTHONPATH=src python3 -m android_setup profiles add "{{ name }}"
    fi

profile-edit name:
    PYTHONPATH=src python3 -m android_setup profiles edit "{{ name }}"

profile-remove name:
    PYTHONPATH=src python3 -m android_setup profiles remove "{{ name }}"

download profile:
    PYTHONPATH=src python3 -m android_setup download "{{ profile }}"

verify profile:
    PYTHONPATH=src python3 -m android_setup verify "{{ profile }}"

setup profile *args:
    PYTHONPATH=src python3 -m android_setup setup "{{ profile }}" {{ args }}

check:
    ruff format --check src tests
    ruff check src tests
    mypy src
    PYTHONPATH=src python3 -m android_setup profiles validate

test-unit:
    PYTHONPATH=src pytest -m "not integration and not workflow and not live" tests

test-integration:
    PYTHONPATH=src pytest -m integration tests

test-workflow:
    PYTHONPATH=src pytest -m workflow tests

test: check
    PYTHONPATH=src pytest -m "not live" --cov=android_setup --cov-branch --cov-report=term-missing tests

test-live:
    ANDROID_SETUP_LIVE=1 PYTHONPATH=src pytest -m live -v tests/test_live.py
