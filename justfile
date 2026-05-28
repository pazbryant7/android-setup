# android-setup justfile
# Install just: https://github.com/casey/just

apks_dir := "apks"
backups_dir := "backups"

# List available recipes
default:
    @just --list

# ── Docker ────────────────────────────────────────────────────────────────────

# Build the Docker image and run the download test
test:
    docker compose -f docker/docker-compose.yml up --build
    docker compose -f docker/docker-compose.yml down

# ── Downloads ─────────────────────────────────────────────────────────────────

# Download latest APKs and backups (skips if files already exist)
download:
    python3 scripts/download.py

# Force redownload — removes existing apks and backups first
redownload:
    rm -rf {{ apks_dir }} {{ backups_dir }}
    python3 scripts/download.py

# ── ADB ───────────────────────────────────────────────────────────────────────

# Run the full ADB setup (install APKs, push files, create dirs)
setup: download
    ./scripts/adb-setup
