"""Phase 1 Test: Architecture invariants audit tests."""

import inspect
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

def test_no_docx_statistical_module():
    """docx_statistical.py must not exist or be imported anywhere in the service."""
    assert not (SCRIPTS_DIR / "docx_statistical.py").exists(), "docx_statistical.py must be removed"
    
    # Check all python files in service/scripts for docx_statistical import
    for py_file in SCRIPTS_DIR.glob("**/*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        assert "docx_statistical" not in content, f"Found docx_statistical reference in {py_file}"

def test_clean_docx_signature_defaults():
    """clean_docx must default to normalize_spaces=False for lossless processing."""
    import container_meta
    sig = inspect.signature(container_meta.clean_docx)
    assert "normalize_spaces" in sig.parameters
    assert sig.parameters["normalize_spaces"].default is False, "clean_docx must default normalize_spaces=False"
    assert sig.parameters["also_layer_a_text"].default is True

def test_docx_cleaner_no_llm_imports():
    """docx package must not import any external AI/LLM client or subprocess."""
    import docx.cleaner
    import docx.detector
    import docx.patcher
    import docx.validator
    import docx.visible_text
    
    for mod in (docx.cleaner, docx.detector, docx.patcher, docx.validator, docx.visible_text):
        mod_src = inspect.getsource(mod)
        assert "ollama" not in mod_src.lower()
        assert "openai" not in mod_src.lower()
        assert "qwen" not in mod_src.lower()
        assert "rewrite_text" not in mod_src

def test_web_app_no_statistical_rewrite_default():
    """service/web/app.js must not force statistical_rewrite: true on DOCX uploads."""
    app_js = (REPO_ROOT / "service" / "web" / "app.js").read_text(encoding="utf-8")
    assert "statistical_rewrite: true" not in app_js
