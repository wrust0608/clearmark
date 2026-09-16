"""Tests for Phase 10: UI and Launcher Scripts Integrity."""

from __future__ import annotations

from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_app_js_docx_options_and_no_statistical_rewrite():
    """Verify app.js does not send statistical_rewrite and enforces normalize_spaces=false for DOCX."""
    app_js_path = ROOT / "service" / "web" / "app.js"
    assert app_js_path.exists()
    content = app_js_path.read_text(encoding="utf-8")

    # Banned destructive flag
    assert "statistical_rewrite: true" not in content
    assert "statistical_rewrite:true" not in content

    # Enforce safe lossless options for DOCX
    assert "normalize_spaces: false" in content
    assert "also_layer_a_text: true" in content


def test_app_js_has_zero_external_telemetry():
    """Verify app.js contains zero external telemetry or tracking scripts."""
    app_js_path = ROOT / "service" / "web" / "app.js"
    content = app_js_path.read_text(encoding="utf-8")

    for domain in ("google-analytics", "doubleclick", "facebook", "mixpanel", "sentry.io", "segment.io"):
        assert domain not in content


def test_launcher_scripts_do_not_force_ollama_or_model_download():
    """Verify launcher scripts run natively without forcing external LLM downloads."""
    for script_name in ("ClearMark.cmd", "clearmark-manager.ps1", "start-app.ps1"):
        script_path = ROOT / script_name
        if script_path.exists():
            content = script_path.read_text(encoding="utf-8", errors="ignore")
            assert "ollama pull" not in content.lower()
            assert "ollama run" not in content.lower()
            # Must not throw when model is missing
            assert 'throw "Thieu bo may xu ly watermark thong ke' not in content
