from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from android_setup.adb import AdbClient
from android_setup.artifacts import ArtifactManager
from android_setup.errors import AndroidSetupError, ConfigError
from android_setup.models import AppSpec, FileSpec, SourceSpec
from android_setup.providers import ProviderRegistry
from android_setup.store import ProfileStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="android-setup", description="Profile-based Android provisioning"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(os.environ.get("ANDROID_SETUP_ROOT", ".")),
        help="repository/configuration root (default: current directory)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    profiles = subparsers.add_parser("profiles", help="manage profiles")
    profile_commands = profiles.add_subparsers(dest="action", required=True)
    profile_commands.add_parser("list")
    show = profile_commands.add_parser("show")
    show.add_argument("profile")
    add = profile_commands.add_parser("add")
    add.add_argument("profile")
    add.add_argument("--from", dest="from_profile")
    edit = profile_commands.add_parser("edit")
    edit.add_argument("profile")
    remove = profile_commands.add_parser("remove")
    remove.add_argument("profile")
    remove.add_argument("--yes", action="store_true")
    validate = profile_commands.add_parser("validate")
    validate.add_argument("profile", nargs="?")

    apps = subparsers.add_parser("apps", help="search and manage apps")
    app_commands = apps.add_subparsers(dest="action", required=True)
    app_list = app_commands.add_parser("list")
    app_list.add_argument("profile")
    search = app_commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--provider", choices=("fdroid", "apkmirror"), default="fdroid")
    app_add = app_commands.add_parser("add")
    app_add.add_argument("profile")
    app_add.add_argument("--provider", choices=("fdroid", "apkmirror"), required=True)
    app_add.add_argument("--id", required=True)
    app_add.add_argument("--name")
    app_add.add_argument("--package-id", required=True)
    app_add.add_argument("--url", help="direct .apk URL required for APKMirror")
    app_add.add_argument("--certificate-sha256")
    app_remove = app_commands.add_parser("remove")
    app_remove.add_argument("profile")
    app_remove.add_argument("app")

    files = subparsers.add_parser("files", help="manage cloud-backed files")
    file_commands = files.add_subparsers(dest="action", required=True)
    file_list = file_commands.add_parser("list")
    file_list.add_argument("profile")
    file_add = file_commands.add_parser("add")
    file_add.add_argument("profile")
    file_add.add_argument("--provider", choices=("pcloud", "https"), required=True)
    file_add.add_argument("--id", required=True)
    file_add.add_argument("--name", required=True)
    file_add.add_argument("--destination", required=True)
    file_add.add_argument(
        "--type", choices=("binary", "json", "sqlite", "text", "zip"), default="binary"
    )
    file_add.add_argument("--url")
    file_add.add_argument("--filename")
    file_add.add_argument("--pattern")
    file_add.add_argument("--secret-ref")
    file_add.add_argument("--sha256")
    file_add.add_argument("--extract-member")
    file_add.add_argument("--extract-type")
    file_remove = file_commands.add_parser("remove")
    file_remove.add_argument("profile")
    file_remove.add_argument("file")

    devices = subparsers.add_parser("devices", help="list connected ADB devices")
    devices.add_argument("action", choices=("list",), nargs="?", default="list")
    devices.add_argument("--adb", default="adb")

    download = subparsers.add_parser("download", help="download and validate artifacts")
    download.add_argument("profile")
    verify = subparsers.add_parser("verify", help="verify cached profile artifacts")
    verify.add_argument("profile")
    setup = subparsers.add_parser("setup", help="provision a connected phone")
    setup.add_argument("profile")
    setup.add_argument("--device")
    setup.add_argument("--adb", default="adb")
    setup.add_argument("--dry-run", action="store_true")
    setup.add_argument("--non-interactive", action="store_true")
    setup.add_argument("--skip-download", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = ProfileStore(args.root)
    try:
        return _dispatch(args, store)
    except AndroidSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace, store: ProfileStore) -> int:
    if args.command == "profiles":
        return _profiles(args, store)
    if args.command == "apps":
        return _apps(args, store)
    if args.command == "files":
        return _files(args, store)
    if args.command == "devices":
        for device in AdbClient(args.adb).devices():
            print(f"{device.serial}\t{device.state}\t{device.model}")
        return 0
    profile = store.load(args.profile)
    base = store.load_base()
    artifacts = ArtifactManager(store.root)
    if args.command == "download":
        records = artifacts.download(profile, base, store.secrets(profile.name))
        for record in records:
            print(f"verified {record.kind} {record.id}: {record.path}")
        return 0
    if args.command == "verify":
        records = artifacts.verify(profile, base)
        print(f"verified {len(records)} artifact(s) for {profile.name}")
        return 0
    if args.command == "setup":
        if not args.skip_download:
            artifacts.download(profile, base, store.secrets(profile.name))
        adb = AdbClient(args.adb, dry_run=args.dry_run)
        device = adb.select_device(args.device, non_interactive=args.non_interactive)
        print(f"Provisioning {device.model} ({device.serial}) with {profile.name}")
        adb.provision(profile, base, artifacts, device)
        print(f"Provisioning completed for {profile.name}")
        return 0
    raise ConfigError(f"unhandled command: {args.command}")


def _profiles(args: argparse.Namespace, store: ProfileStore) -> int:
    if args.action == "list":
        for profile in store.list():
            print(f"{profile.name}\t{profile.description}")
    elif args.action == "show":
        profile = store.load(args.profile)
        data = profile.to_dict()
        data["effective_apps"] = [
            app.to_dict() for app in profile.effective_apps(store.load_base())
        ]
        print(json.dumps(data, indent=2))
    elif args.action == "add":
        profile = store.add(args.profile, args.from_profile)
        print(f"created profile {profile.name}")
    elif args.action == "edit":
        store.edit(args.profile)
        print(f"updated profile {args.profile}")
    elif args.action == "remove":
        if not args.yes:
            answer = input(f"Remove profile {args.profile!r}? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("cancelled")
                return 1
        store.remove(args.profile)
        print(f"removed profile {args.profile}")
    elif args.action == "validate":
        profiles = [store.load(args.profile)] if args.profile else store.list()
        base = store.load_base()
        for profile in profiles:
            profile.effective_apps(base)
            print(f"valid: {profile.name}")
    return 0


def _apps(args: argparse.Namespace, store: ProfileStore) -> int:
    providers = ProviderRegistry()
    if args.action == "search":
        for result in providers.search(args.query, args.provider):
            print(f"{result.name}\t{result.identifier}\t{result.url}")
        return 0
    profile = store.load(args.profile)
    base = store.load_base()
    if args.action == "list":
        required = {app.id for app in base.required_apps}
        for app in profile.effective_apps(base):
            marker = "required" if app.id in required else "profile"
            print(f"{app.id}\t{app.package_id}\t{marker}")
        return 0
    if args.action == "add":
        if args.provider == "fdroid":
            found_name, package_id = providers.fdroid_app(args.package_id)
            source = SourceSpec(
                "fdroid",
                {"repo_url": "https://f-droid.org/repo", "package_id": package_id},
            )
            name = args.name or found_name
        else:
            if not args.url:
                raise ConfigError("APKMirror apps require a selected direct --url")
            if not args.url.lower().endswith(".apk"):
                raise ConfigError("APKMirror v1 accepts direct .apk URLs only")
            source = SourceSpec("https", {"url": args.url})
            name = args.name or args.id
        app = AppSpec.from_dict(
            {
                "id": args.id,
                "name": name,
                "package_id": args.package_id,
                "source": source.to_dict(),
                "certificate_sha256": args.certificate_sha256,
            }
        )
        updated = replace(profile, apps=(*profile.apps, app))
        store.save(updated)
        print(f"added app {app.id} to {profile.name}")
        return 0
    if args.action == "remove":
        if args.app in {app.id for app in base.required_apps}:
            raise ConfigError(f"required app cannot be removed: {args.app}")
        apps = tuple(app for app in profile.apps if app.id != args.app)
        if len(apps) == len(profile.apps):
            raise ConfigError(f"profile app not found: {args.app}")
        store.save(replace(profile, apps=apps))
        print(f"removed app {args.app} from {profile.name}")
        return 0
    raise ConfigError(f"unhandled apps action: {args.action}")


def _files(args: argparse.Namespace, store: ProfileStore) -> int:
    profile = store.load(args.profile)
    if args.action == "list":
        for item in profile.files:
            print(f"{item.id}\t{item.source.provider}\t{item.destination}")
        return 0
    if args.action == "add":
        if args.provider == "https":
            if not args.url:
                raise ConfigError("HTTPS files require --url")
            source_options = {"url": args.url}
            if args.filename:
                source_options["filename"] = args.filename
        else:
            if not args.pattern or not args.secret_ref:
                raise ConfigError("pCloud files require --pattern and --secret-ref")
            source_options = {
                "pattern": args.pattern,
                "secret_ref": args.secret_ref,
                "secret_field": "folder_code",
            }
        item = FileSpec.from_dict(
            {
                "id": args.id,
                "name": args.name,
                "destination": args.destination,
                "type": args.type,
                "source": {"provider": args.provider, **source_options},
                "sha256": args.sha256,
                "extract_member": args.extract_member,
                "extract_type": args.extract_type,
            }
        )
        store.save(replace(profile, files=(*profile.files, item)))
        print(f"added file {item.id} to {profile.name}")
        return 0
    if args.action == "remove":
        files = tuple(item for item in profile.files if item.id != args.file)
        if len(files) == len(profile.files):
            raise ConfigError(f"profile file not found: {args.file}")
        store.save(replace(profile, files=files))
        print(f"removed file {args.file} from {profile.name}")
        return 0
    raise ConfigError(f"unhandled files action: {args.action}")
