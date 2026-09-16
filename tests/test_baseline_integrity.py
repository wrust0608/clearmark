"""Phase 0 Test: Baseline integrity check for repository and environment."""

import hashlib
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

def test_repo_root_exists():
    assert REPO_ROOT.exists()
    assert (REPO_ROOT / "service" / "scripts").exists()
    assert (REPO_ROOT / "tests").exists()
    assert (REPO_ROOT / "MASTER_IMPLEMENTATION_PLAN.md").exists()

def test_python_version():
    # Requires Python 3.10+
    assert sys.version_info >= (3, 10)

def test_core_modules_importable():
    sys.path.insert(0, str(REPO_ROOT / "service" / "scripts"))
    import container_meta
    import text_unicode
    import format_dispatch
    import docx
    assert hasattr(docx, "clean_docx_lossless")
    assert hasattr(container_meta, "clean_docx")
