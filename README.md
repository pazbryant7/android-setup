# android-setup

Automated scripts to bootstrap a new Android device from scratch using ADB, Shizuku, Obtanium and FolderSync.

---

## How it works

The setup is split into two phases:

1. **Computer phase** — download APKs and backups, then push everything to the phone via ADB
2. **Phone phase** — restore backups, run syncs, batch install apps

```
Computer
  └── download.py        → pulls latest APKs from GitHub,
  │                         backups from pCloud
  └── adb_setup.sh       → installs APKs, pushes backups, creates dirs on phone

Phone (manual)
  └── Shizuku pair + start
  └── FolderSync restore + run syncs
  └── Obtanium restore + batch install
  └── xPass restore
```

---

## Prerequisites

| Tool      | Purpose                                       |
| --------- | --------------------------------------------- |
| `adb`     | Android Debug Bridge — communicate with phone |
| `curl`    | Download files                                |
| `python3` | Parse pCloud API responses, scrape pages      |

Install on Debian/Ubuntu: `sudo apt install adb curl python3`

---

## Repository structure

```
android-setup/
├── scripts/
│   ├── lib.py          # Shared utilities, logging, archive extraction helpers
│   └── adb_setup.sh    # ADB install + push + create dirs
├── docker/
│   ├── Dockerfile      # Minimal Alpine image for download testing
│   └── compose.yml     # Docker Compose for easy test run
├── apks/               # Downloaded APKs (git-ignored)
├── backups/            # Downloaded backups, extracted (git-ignored)
└── .gitignore
```

---

## Step-by-step setup

### Phase 1 — Computer (one sitting)

#### Step 1 — Clone this repo

```sh
git clone https://github.com/YOUR_USERNAME/android-setup.git
cd android-setup
chmod +x scripts/*.sh
```

#### Step 2 — Download APKs, backups

```sh
python3 scripts/download.py
```

This fetches:

- `apks/shizuku-v*.apk` — latest from [RikkaApps/Shizuku](https://github.com/RikkaApps/Shizuku)
- `apks/app-arm64-v8a-release.apk` — latest arm64 from [ImranR98/Obtainium](https://github.com/ImranR98/Obtainium)
- `backups/obtainium-export-*.json` — most recent export from your pCloud folder
- `backups/foldersync.db` — extracted from the pCloud zip backup (archive is removed after extraction)

#### Step 3 — Enable Wireless Debugging on the phone

On the phone:
`Settings → Developer Options → Wireless Debugging → Enable`

#### Step 4 — Pair ADB with the phone

```sh
adb pair <ip>:<port>
# Enter the pairing code shown on the phone
adb connect <ip>:5555
adb devices  # confirm device shows as "device"
```

#### Step 5 — Run the ADB setup

```sh
./scripts/adb_setup.sh
```

This does:

- Installs Shizuku, Obtanium APKs
- Creates required directories on the phone
- Pushes APKs, Obtanium backup JSON, and the extracted FolderSync `.db` to `/sdcard/Download/`

---

### Phase 2 — Phone only

#### Step 6 — Start Shizuku

1. Open **Shizuku**
2. Tap **"Pair using Wireless Debugging"**
3. Follow the pairing prompt
4. Tap **Start** — Shizuku service is now running

> Enable **"Start on boot"** in Shizuku settings so it auto-starts after reboots.

#### Step 7 — Restore FolderSync and run syncs

1. Open **FolderSync**
2. Go to **Settings → Backup → Restore**
3. Select `foldersync.db` from `/sdcard/Download/`
4. Go to **Sync pairs** → run all pairs

> All local directories were already created by `adb_setup.sh` so syncs should run cleanly.

#### Step 8 — Restore Obtanium and install apps

1. Open **Obtanium**
2. Tap **Import/Export → Import**
3. Select `obtainium-export-*.json` from `/sdcard/Download/`
4. Tap **Install all** — Shizuku handles silent install

---

## Adding support for new backup archive formats

`download.py` extracts FolderSync (and any future archive-based backup) using the
`ARCHIVE_EXTRACTORS` registry in `scripts/lib.py`. It supports `.zip`, `.tar`,
`.tar.gz`, `.tgz`, `.tar.bz2`, and `.tar.xz` out of the box.

To add a new format (e.g. RAR):

```python
# In scripts/lib.py
import rarfile  # pip install rarfile

def _extract_rar(archive: Path, dest: Path) -> list[Path]:
    with rarfile.RarFile(archive) as rf:
        rf.extractall(dest)
        return [dest / n for n in rf.namelist()]

ARCHIVE_EXTRACTORS[".rar"] = _extract_rar
```

Then update `FOLDERSYNC_BACKUP_PATTERN` in `download.py` to match the new filename:

```python
FOLDERSYNC_BACKUP_PATTERN = "foldersync.db.rar"
```

---

## Testing downloads (Docker)

To verify the download logic works without touching a phone:

```sh
cd docker
docker compose up --build
```

Downloaded files will be placed in `apks/`, `backups/` (mounted as volumes). Inspect them after the run:

```sh
ls -lh ../apks/ ../backups/
```

Or build and run manually:

```sh
docker build -f docker/Dockerfile -t android-setup-test .
docker run --rm \
  -v "$(pwd)/apks:/app/apks" \
  -v "$(pwd)/backups:/app/backups" \
  android-setup-test
```

---

## Customising directories

Edit `PHONE_DIRS` in `scripts/adb_setup.sh` to match your FolderSync pair structure:

```sh
PHONE_DIRS="
/sdcard/Music
/sdcard/Pictures
/sdcard/DCIM
/sdcard/YourCustomFolder
"
```

---

## What remains manual

| Step                        | Why                                                                   |
| --------------------------- | --------------------------------------------------------------------- |
| ADB pair (step 4)           | Android requires a tap-to-confirm on the device — cannot be automated |
| Shizuku start (step 6)      | Wireless debugging pairing requires UI interaction                    |
| Restore backups (steps 7–9) | App UI required; no CLI interface available                           |
