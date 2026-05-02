import os
import sys
import shutil
import subprocess
import json
from pathlib import Path
from datetime import datetime

# =====================================================================
# CONFIGURATION
# =====================================================================
MACHINE_INDEX = int(os.environ.get("MACHINE_INDEX", "0"))
TOTAL_MACHINES = int(os.environ.get("TOTAL_MACHINES", "20"))
UPLOAD_TRANSFERS = 2

BASE_DIR = Path(".")
INPUTS_DIR = BASE_DIR / "Inputs"
DATASETS_DIR = BASE_DIR / "datasets"

now = datetime.now()
BATCH_FOLDER = BASE_DIR / f"Batch--{now.strftime('%Y-%m-%d')}--node{MACHINE_INDEX}"

def log(msg):
    print(f"[Node {MACHINE_INDEX:02d}] {msg}", flush=True)

# =====================================================================
# NODE REPORTING
# =====================================================================
def create_node_report(batch_folder, primary_acc, final_acc, status, file_count):
    report_file = BASE_DIR / f"NodeReport_{MACHINE_INDEX}.json"
    data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "node": MACHINE_INDEX,
        "batch_folder": batch_folder,
        "primary_assigned_acc": primary_acc,
        "final_uploaded_acc": final_acc,
        "status": status,
        "files_count": file_count
    }
    with open(report_file, 'w') as f:
        json.dump(data, f, indent=4)
    log(f"📝 Report saved: {report_file.name}")

# =====================================================================
# EXTRACTION MODE
# =====================================================================
def run_extraction():
    all_files = sorted(list(INPUTS_DIR.rglob("*.json")))
    
    # In files ko touch nahi karna
    skip_names = {"resume_state.json", "package.json", "package-lock.json", "session_mapping.json", "session_mapping_backup.json"}
    all_files = [f for f in all_files if f.name not in skip_names]

    # Mathematical Sharding!
    my_files = [f for i, f in enumerate(all_files) if i % TOTAL_MACHINES == MACHINE_INDEX]
    
    if not my_files:
        log("⚠️ No files assigned to this node.")
        return

    DATASETS_DIR.mkdir(exist_ok=True)
    BATCH_FOLDER.mkdir(exist_ok=True)

    log(f"📦 Copying {len(my_files)} files to datasets/...")
    for f in my_files:
        shutil.copy2(f, DATASETS_DIR / f.name)

    # 🚀 FIX 1: Protect mapping file from being moved by the extractor
    if Path("session_mapping.json").exists():
        shutil.copy2("session_mapping.json", "session_mapping_backup.json")
        log("🔒 session_mapping.json ka backup bana liya gaya hai.")

    # 🚀 FIX 2: Isolate the node by deleting unassigned files from Inputs/
    log("🧹 Clearing unassigned files from Inputs/ to protect sharding...")
    for f in INPUTS_DIR.rglob("*.json"):
         if f.name not in skip_names:
            try: f.unlink()
            except: pass

    # Run original extraction script
    env = os.environ.copy()
    env["OUTPUT_FOLDER"] = str(BATCH_FOLDER)
    env["INPUT_FOLDER"] = str(DATASETS_DIR)
    env["MAX_WORKERS"] = "30"

    log("🚀 Running tor-colab-data-caption-follower-extract.py...")
    res = subprocess.run([sys.executable, "tor-colab-data-caption-follower-extract.py"], env=env)
    
    if res.returncode != 0:
        log("❌ Extraction failed.")
        sys.exit(1)
    log("✅ Extraction done.")

# =====================================================================
# UPLOAD MODE
# =====================================================================
def upload_data():
    if not BATCH_FOLDER.exists(): 
        log("⚠️ Batch folder nahi mila, upload skip kar raha hun.")
        return
    
    # 🚀 FIX 3: Read from backup mapping if original is moved
    map_file = "session_mapping.json"
    if not Path(map_file).exists() and Path("session_mapping_backup.json").exists():
        map_file = "session_mapping_backup.json"
        log("🔄 Backup mapping file use kar raha hun.")

    my_accounts = []
    primary_acc = "N/A"
    
    try:
        with open(map_file, "r") as f:
            mapping = json.load(f)
            my_accounts = mapping.get(str(MACHINE_INDEX), [])
            if my_accounts: primary_acc = my_accounts[0]
    except Exception as e:
        log(f"⚠️ Mapping load nahi hui: {e}. Falling back to default.")
        # Agar koi ghalti ho toh simple index use kar lega
        my_accounts = [f"insta_acc_{MACHINE_INDEX}", f"insta_acc_{(MACHINE_INDEX+20)%49}", f"insta_acc_{(MACHINE_INDEX+40)%49}"]
        primary_acc = my_accounts[0]

    if not my_accounts:
        log("❌ No accounts assigned to this node! Check mapping.")
        sys.exit(1)

    remote_name = BATCH_FOLDER.name
    local_path = str(BATCH_FOLDER)
    file_count = sum(1 for _ in BATCH_FOLDER.rglob("*") if _.is_file())
    
    final_acc = "NONE"
    status = "FAILED"
    max_attempts = 3

    # SMART FALLBACK LOOP (Limiting to 3 attempts as requested)
    for i in range(min(max_attempts, len(my_accounts))):
        acc = my_accounts[i]
        remote_dest = f"{acc}:Insta_Extracted/{remote_name}"
        log(f"☁️ Uploading to {remote_dest} (Attempt {i+1}/{max_attempts})...")
        
        cmd = ["rclone", "copy", local_path, remote_dest, "--transfers", str(UPLOAD_TRANSFERS), "--retries", "3"]
        res = subprocess.run(cmd)

        if res.returncode == 0:
            log(f"✅ SUCCESS: Data is in {acc}")
            final_acc = acc
            status = "SUCCESS"
            break
        else:
            log(f"⚠️ ERROR: Failed on {acc} (Quota full/Dead).")

    create_node_report(remote_name, primary_acc, final_acc, status, file_count)
    
    if status == "FAILED":
        log("❌ FATAL: All assigned accounts failed!")
        sys.exit(1)

# =====================================================================
# MAIN EXECUTION
# =====================================================================
if __name__ == "__main__":
    mode = sys.argv[2] if len(sys.argv) > 2 else "upload"
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode")+1]

    if mode == "extract": run_extraction()
    elif mode == "upload": upload_data()
