# android-setup

A profile-based CLI for provisioning Android phones through ADB. Profiles declare
apps, directories, backups, configuration files, and manual follow-up steps. Every
download is isolated by profile and must pass validation before installation.

## Initial profiles

| Profile | Apps | Profile data |
| --- | --- | --- |
| `personal` | Obtainium, Brave, MiXplorer, Shizuku | Existing directories, Obtainium backup, FolderSync database |
| `work` | Obtainium, Brave, MiXplorer | None initially |
| `business` | Obtainium, Brave, MiXplorer | None initially |

The three shared apps are defined in `profiles/base.json` and cannot be removed.
Profile-specific configuration lives in `profiles/<name>.json`. Downloaded files
are stored under `artifacts/<name>/` and are ignored by Git.

## Development setup

```sh
nix develop
just check
```

The `just` recipes run the package directly from `src/`. Outside Nix, install the
console command with `python3 -m pip install -e '.[dev]'`.

APK identity checks require `aapt` and `apksigner`. ADB setup additionally
requires Android Platform Tools and an authorized, non-production phone.

## Profile management

```sh
android-setup profiles list
android-setup profiles show personal
android-setup profiles add travel
android-setup profiles add personal-copy --from personal
android-setup profiles edit travel
android-setup profiles remove travel
android-setup profiles validate
```

`profiles edit` opens `$VISUAL` or `$EDITOR` and commits the edit only after the
result validates. Removal requires confirmation unless `--yes` is supplied.

Private pCloud folder codes belong in `profiles/.secrets/<profile>.json`; copy
`profiles/.secrets.example.json` as a starting point. Never commit this directory.

## Apps and cloud files

Search F-Droid or APKMirror from the CLI:

```sh
android-setup apps search aegis --provider fdroid
android-setup apps search signal --provider apkmirror
android-setup apps add work --provider fdroid \
  --id aegis --package-id com.beemdevelopment.aegis
```

F-Droid results can be resolved and downloaded automatically. APKMirror search
returns release pages; adding an APKMirror result requires a manually selected
direct `.apk` URL, package ID, and preferably its certificate SHA-256. Split APK,
APKS, and XAPK bundles are intentionally rejected in this release.

Profiles can receive files from HTTPS or pCloud:

```sh
android-setup files add work --provider https --id policy \
  --name 'Work policy' --type json --destination /sdcard/Work \
  --url https://example.com/policy.json
```

Supported validation types are `binary`, `json`, `sqlite`, `text`, and `zip`.
ZIP sources can select one member with `extract_member` and validate the result
using `extract_type`.

## Download and provision

```sh
android-setup download personal
android-setup verify personal
android-setup devices list
android-setup setup personal --device SERIAL
```

If several devices are connected, `setup` prompts for one unless `--device` is
provided. Automation should also pass `--non-interactive`. Use `--dry-run` to
print mutating ADB operations after artifact validation. Existing launchers remain
available as `scripts/download.py PROFILE` and `scripts/adb-setup PROFILE`.

## Tests

```sh
just test-unit       # models, providers, validation, CLI, and ADB behavior
just test-integration # local HTTP downloads and artifact lifecycle
just test-workflow   # complete Personal/Work/Business runs with fake ADB
just test            # lint, type checks, all hermetic tests, coverage
just test-live       # opt-in real provider downloads; requires Android tools
```

Pull requests run only deterministic tests. Live provider checks are intended for
manual or scheduled CI. Real-device setup is never executed in normal CI.
