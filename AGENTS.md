# Repository Guidelines

## Project Structure & Module Organization

This repository automates first-time Android device setup. Core automation is in `scripts/`: `download.py` retrieves APKs and pCloud backups, `lib.py` contains shared network, logging, and archive helpers, and `adb-setup` installs and transfers files through ADB. Containerized download checks live in `docker/`. `flake.nix` defines the Nix development shell and `justfile` provides common task aliases. The generated `apks/` and `backups/` directories are intentionally ignored; do not commit downloaded APKs, backups, or device-specific data.

## Build, Test, and Development Commands

- `nix develop` enters the pinned shell with `android-tools`, `just`, and `typos`.
- `just download` runs `python3 scripts/download.py` and preserves existing APKs when possible.
- `just test` builds the Docker image and runs the download workflow; it tears down the Compose stack afterward.
- `just setup` downloads required files, then runs `./scripts/adb-setup` against the paired device.
- `nix fmt` formats Nix files with the repository formatter.

Avoid `just redownload` unless a clean re-fetch is intended: it removes the local generated download directories first.

## Coding Style & Naming Conventions

Use Python 3 standard-library solutions where practical. Follow existing Python conventions: four-space indentation, `snake_case` functions and variables, `UPPER_SNAKE_CASE` module configuration, `Path` for filesystem paths, and type annotations on new functions. Keep network failures recoverable and report them through the existing `log_*` helpers. Write POSIX shell for `scripts/adb-setup`; retain its tab indentation and quote variable expansions. Name backup patterns and device paths descriptively, such as `FOLDERSYNC_BACKUP_PATTERN` and `PHONE_DOWNLOAD`.

## Testing Guidelines

There is no unit-test suite currently. Before submitting download-related changes, run `just test` to exercise the containerized workflow, then inspect `apks/` and `backups/` as needed. For ADB changes, verify with `adb devices` and test only against a paired, non-production device when possible. Do not run device setup commands in CI.

## Commit & Pull Request Guidelines

Use concise Conventional Commit-style subjects consistent with history: `feat(nix): add a development shell` or `fix(docker-compose): correct volume path`. Keep commits focused. Pull requests should explain the affected setup phase, link relevant issues, identify any required secrets or manual phone steps, and include terminal output or screenshots when behavior changes. Never expose pCloud links, backups, or other personal device data in a PR.
