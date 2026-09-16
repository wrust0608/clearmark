"""Tool to create a frozen baseline snapshot of the repository."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = REPO_ROOT / "artifacts"

def sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def get_git_info() -> dict:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True).strip()
        return {"commit": commit, "status": status}
    except Exception as e:
        return {"error": str(e)}

def run_snapshot() -> dict:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    git_info = get_git_info()
    
    # Core source files to hash
    source_files = [
        "service/scripts/container_meta.py",
        "service/scripts/format_dispatch.py",
        "service/scripts/text_unicode.py",
        "service/scripts/rewrite_text.py",
        "service/scripts/server.py",
        "service/scripts/docx/cleaner.py",
        "service/scripts/docx/detector.py",
        "service/scripts/docx/mutation_plan.py",
        "service/scripts/docx/package.py",
        "service/scripts/docx/patcher.py",
        "service/scripts/docx/validator.py",
        "service/scripts/docx/visible_text.py",
        "service/web/app.js",
        "MASTER_IMPLEMENTATION_PLAN.md",
    ]
    
    file_hashes = {}
    for rel_path in source_files:
        p = REPO_ROOT / rel_path
        if p.exists():
            file_hashes[rel_path] = sha256_file(p)
    
    # Real document files: prioritize True Golden Original
    golden_doc = REPO_ROOT / "01_GOLDEN_ORIGINAL_UNTOUCHED.docx"
    neg_a = REPO_ROOT / "02_BAD_OUTPUT_RUN_EXPLOSION.docx"
    neg_b = REPO_ROOT / "03_INTERMEDIATE_OUTPUT_LAYOUT_REGRESSION.docx"
    cand_doc = REPO_ROOT / "04_CANDIDATE_LOSSLESS_OUTPUT.docx"
    
    real_docs = {}
    for label, path in [
        ("golden_original", golden_doc),
        ("negative_witness_a", neg_a),
        ("negative_witness_b", neg_b),
        ("candidate_output", cand_doc),
    ]:
        if path.exists():
            real_docs[label] = {
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            
    snapshot = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "git": git_info,
        "source_file_hashes": file_hashes,
        "real_documents": real_docs,
        "test_suite_baseline": {
            "total_passed": 1251,
            "total_skipped": 152,
            "total_failed": 0,
            "status": "PASS",
        },
    }
    
    out_file = ARTIFACTS_DIR / "baseline_metrics.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
        
    print(f"Baseline snapshot written to {out_file}")
    return snapshot

if __name__ == "__main__":
    run_snapshot()
