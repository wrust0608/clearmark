"""Phase 2 Test: Per-format policy specifications and enforcement."""

import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "service" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from format_policy import (
    FormatCategory,
    FormatFidelityPolicy,
    get_format_policy,
    resolve_options_for_format,
)

def test_docx_policy_invariants():
    policy = get_format_policy("docx")
    assert policy.category == FormatCategory.WORD_PROCESSING
    assert policy.default_normalize_spaces is False, "DOCX must never normalize NBSP by default"
    assert policy.allow_llm_rewrite is False, "LLM rewrite is banned on DOCX"
    assert policy.structural_invariants_required is True
    assert policy.fail_closed is True

def test_plain_text_policy():
    policy = get_format_policy("txt")
    assert policy.category == FormatCategory.PLAIN_TEXT
    assert policy.default_normalize_spaces is True
    assert policy.allow_llm_rewrite is True

def test_media_policies():
    for ext in ("png", "jpeg", "webp", "mp4", "mp3"):
        policy = get_format_policy(ext)
        assert policy.category in (FormatCategory.RASTER_IMAGE, FormatCategory.AUDIO_VIDEO)
        assert policy.allow_llm_rewrite is False
        assert policy.strip_metadata_only is True

def test_resolve_options_docx_enforces_safety():
    # If a caller passes normalize_spaces=True or statistical_rewrite=True to DOCX,
    # the policy resolver must enforce safety
    opts = resolve_options_for_format("docx", {"statistical_rewrite": True})
    assert opts.get("statistical_rewrite", False) is False, "statistical_rewrite must be stripped/disabled for DOCX"
    assert opts.get("normalize_spaces") is False
    assert opts.get("also_layer_a_text") is True
