#!/usr/bin/env python3
"""
worker.py — Matrix Node Worker
  --mode extract  : Apni assigned JSON files extract karo
  --mode upload   : Extracted Batch folder Mega pe upload karo

Env vars (GitHub Actions se aate hain):
  MACHINE_INDEX    : 0-based index (0, 1, 2 ...)
  TOTAL_MACHINES   : total nodes (e.g. 20)
  ZIP_ENABLED      : true/false
  ZIP_FILE_LIMIT   : files count threshold for zipping (default 1300)
  UPLOAD_TRANSFERS : rclone --transfers value (default 2)
"""

import os
import sys
import glob
import json
import math
import shutil
import zipfile
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# ════════════════════════════════════════════════════════════════════
#  CONFIG — ENV se lo
# ════════════════════════════════════════════════════════════════════
MACHINE_INDEX    = int(os.environ.get("MACHINE_INDEX",   "0"))
TOTAL_MACHINES   = int(os.environ.get("TOTAL_MACHINES",  "1"))
ZIP_ENABLED      = os.environ.get("ZIP_ENABLED",  "true").lower() == "true"
ZIP_FILE_LIMIT   = int(os.environ.get("ZIP_FILE_LIMIT",  "1300"))
UPLOAD_TRANSFERS = int(os.environ.get("UPLOAD_TRANSFERS", "2"))

BASE_DIR      = Path(".")
INPUTS_DIR    = BASE_DIR / "Inputs"
DATASETS_DIR  = BASE_DIR / "datasets"

# Is node ka unique batch folder
now = datetime.now()
BATCH_NAME   = f"Batch--{now.strftime('%Y-%m-%d-%A_%I-%M-%S-%p')}--node{MACHINE_INDEX}"
BATCH_FOLDER = BASE_DIR / BATCH_NAME

# Original script ka MAX_WORKERS
MAX_WORKERS = 30

# ════════════════════════════════════════════════════════════════════
#  LOGGING HELPERS
# ════════════════════════════════════════════════════════════════════
def log(msg):
    prefix = f"[Node {MACHINE_INDEX:02d}/{TOTAL_MACHINES}]"
    print(f"{prefix} {msg}", flush=True)

def log_sep(char="═", n=60):
    print(char * n, flush=True)

def log_header(title):
    log_sep()
    log(f"  {title}")
    log_sep()

# ════════════════════════════════════════════════════════════════════
#  SHARDING — Konsi files is node ki hain?
# ════════════════════════════════════════════════════════════════════
def get_my_files() -> list[Path]:
    """
    Sari JSON files lo, phir sirf apni wali lo.
    
    Formula: file_index % TOTAL_MACHINES == MACHINE_INDEX
    
    Example (20 machines, 100 files):
      Node 0  → files[0, 20, 40, 60, 80]
      Node 1  → files[1, 21, 41, 61, 81]
      Node 19 → files[19, 39, 59, 79, 99]
    """
    all_files = sorted(
        list(INPUTS_DIR.glob("*.json")) +
        list(INPUTS_DIR.glob("**/*.json"))
    )
    # resume_state ya special files skip karo
    skip_names = {"resume_state.json", "package.json", "package-lock.json"}
    all_files = [f for f in all_files if f.name not in skip_names]

    total_files = len(all_files)
    my_files = [f for i, f in enumerate(all_files) if i % TOTAL_MACHINES == MACHINE_INDEX]

    log(f"📁 Total files in Inputs/: {total_files}")
    log(f"📂 My assigned files     : {len(my_files)}")
    for i, f in enumerate(my_files):
        log(f"   [{i+1}/{len(my_files)}] {f.name}")

    return my_files

# ════════════════════════════════════════════════════════════════════
#  EXTRACTION MODE
# ════════════════════════════════════════════════════════════════════
def run_extraction(my_files: list[Path]):
    if not my_files:
        log("⚠️  Koi file assigned nahi — skip.")
        return

    log_header(f"EXTRACTION MODE — {len(my_files)} files")

    # datasets/ folder banao aur apni files copy karo
    DATASETS_DIR.mkdir(exist_ok=True)
    BATCH_FOLDER.mkdir(parents=True, exist_ok=True)

    log(f"📦 Apni files datasets/ mein copy kar raha hun...")
    for f in my_files:
        dest = DATASETS_DIR / f.name
        shutil.copy2(f, dest)
        log(f"   ✅ Copied: {f.name}")

    # Original extraction script chalao — env vars pass karo
    env = os.environ.copy()
    env["MAX_WORKERS"]    = str(MAX_WORKERS)      # 30 workers
    env["OUTPUT_FOLDER"]  = str(BATCH_FOLDER)     # is node ka batch folder
    env["INPUT_FOLDER"]   = str(DATASETS_DIR)

    log(f"🚀 Extraction script chala raha hun (MAX_WORKERS={MAX_WORKERS})...")
    log(f"   Output → {BATCH_FOLDER}")

    result = subprocess.run(
        [sys.executable, "tor-colab-data-caption-follower-extract.py"],
        env=env,
        text=True
    )

    if result.returncode != 0:
        log(f"❌ Extraction script failed (exit {result.returncode})")
        sys.exit(1)

    log(f"✅ Extraction complete → {BATCH_FOLDER}")

# ════════════════════════════════════════════════════════════════════
#  ZIP LOGIC — count-based
# ════════════════════════════════════════════════════════════════════
def count_files_recursive(folder: Path) -> int:
    return sum(1 for _ in folder.rglob("*") if _.is_file())

def zip_batch_folder(folder: Path) -> Path:
    """Batch folder ko zip karo, zip path return karo."""
    zip_path = folder.parent / f"{folder.name}.zip"
    log(f"🗜️  ZIP banana shuru: {folder.name}.zip")

    file_list = list(folder.rglob("*"))
    total = sum(1 for f in file_list if f.is_file())
    done = 0

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in file_list:
            if item.is_file():
                arcname = item.relative_to(folder.parent)
                zf.write(item, arcname)
                done += 1
                if done % 100 == 0 or done == total:
                    pct = int(done / total * 100)
                    log(f"   🗜️  Zipping... {done}/{total} ({pct}%)")

    size_mb = zip_path.stat().st_size / 1024 / 1024
    log(f"   ✅ ZIP ready: {zip_path.name} ({size_mb:.1f} MB)")
    return zip_path

# ════════════════════════════════════════════════════════════════════
#  UPLOAD MODE
# ════════════════════════════════════════════════════════════════════
def run_upload():
    log_header(f"UPLOAD MODE — Mega pe bhejenge")

    # Is node ka batch folder dhoondo
    batch_dirs = sorted(BASE_DIR.glob(f"Batch--*--node{MACHINE_INDEX}"))

    if not batch_dirs:
        log("⚠️  Koi Batch folder nahi mila — extraction hua tha?")
        return

    for batch_folder in batch_dirs:
        upload_single_batch(batch_folder)

def upload_single_batch(batch_folder: Path):
    log_sep("─")
    log(f"📂 Batch folder: {batch_folder.name}")

    file_count = count_files_recursive(batch_folder)
    log(f"📊 Files in batch: {file_count}")
    log(f"📊 ZIP threshold : {ZIP_FILE_LIMIT}")
    log(f"📊 ZIP enabled   : {ZIP_ENABLED}")

    # ZIP decision
    should_zip = ZIP_ENABLED and (file_count > ZIP_FILE_LIMIT)

    if should_zip:
        log(f"🗜️  Files ({file_count}) > limit ({ZIP_FILE_LIMIT}) → ZIP karega")
        upload_target = zip_batch_folder(batch_folder)
        upload_type   = "ZIP"
        remote_name   = upload_target.name
        local_path    = str(upload_target)
        rclone_mode   = "copyto"   # single file
    else:
        if ZIP_ENABLED:
            log(f"📁 Files ({file_count}) ≤ limit ({ZIP_FILE_LIMIT}) → seedha upload")
        else:
            log(f"📁 ZIP disabled → seedha upload")
        upload_target = batch_folder
        upload_type   = "DIR"
        remote_name   = batch_folder.name
        local_path    = str(batch_folder)
        rclone_mode   = "copy"     # folder

    # Mega remote name — rclone.conf se "ext" remote use kar raha hai (original se)
    remote_dest = f"ext:Extracted_Data/{remote_name}"

    log(f"☁️  Upload type  : {upload_type}")
    log(f"☁️  Local        : {local_path}")
    log(f"☁️  Remote       : {remote_dest}")
    log(f"☁️  Transfers    : {UPLOAD_TRANSFERS}")
    log(f"☁️  Upload shuru ...")

    cmd = [
        "rclone", rclone_mode,
        local_path,
        remote_dest,
        "--transfers",     str(UPLOAD_TRANSFERS),
        "--stats",         "15s",          # har 15 sec progress
        "--stats-one-line",                # compact log
        "--retries",       "3",
        "--low-level-retries", "5",
        "--verbose",                       # har file ka naam dikhe
    ]

    log(f"🔧 CMD: {' '.join(cmd)}")
    log_sep("─")

    result = subprocess.run(cmd, text=True)

    log_sep("─")
    if result.returncode == 0:
        log(f"✅ UPLOAD SUCCESS: {remote_name}")
    else:
        log(f"❌ UPLOAD FAILED (exit {result.returncode}): {remote_name}")
        sys.exit(1)

    # ZIP file cleanup (optional — disk space bachao)
    if should_zip and upload_target.exists() and upload_target.suffix == ".zip":
        upload_target.unlink()
        log(f"🧹 ZIP deleted (disk clean): {upload_target.name}")

# ════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["extract", "upload"], required=True)
    args = parser.parse_args()

    log_header(f"WORKER START — mode={args.mode.upper()}")
    log(f"  Machine      : {MACHINE_INDEX} / {TOTAL_MACHINES}")
    log(f"  ZIP enabled  : {ZIP_ENABLED}")
    log(f"  ZIP limit    : {ZIP_FILE_LIMIT} files")
    log(f"  Transfers    : {UPLOAD_TRANSFERS}")
    log(f"  Workers      : {MAX_WORKERS}")
    log_sep()

    if args.mode == "extract":
        my_files = get_my_files()
        run_extraction(my_files)
    elif args.mode == "upload":
        run_upload()

if __name__ == "__main__":
    main()
