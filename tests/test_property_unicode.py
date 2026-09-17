"""Phase 10: Deterministic Unicode Property-Based Testing Harness.

Validates the fundamental text cleaning properties under generative combinations:
1. Primary Idempotence Property: C(C(text)) == C(text)
2. Already-Clean Identity: C(clean_text) == clean_text
3. Contextual Unicode Preservation:
   - Emoji ZWJ sequences (e.g. 👨‍👩‍👧‍👦, 🏳️‍🌈)
   - Arabic / Persian cursive joining contexts (e.g. العربية, سلام)
   - Devanagari conjuncts & virama (e.g. नमस्ते, क्ष)
   - Non-breaking spaces (NBSP U+00A0, NNBSP U+202F)
   - Unicode normalization forms (NFC / NFD)
4. Multi-Carrier One-Pass Convergence:
   - All removable carrier codepoints removed in pass 1
   - Zero removable carrier codepoints remaining in pass 2
   - No progressive/partial stripping across passes
5. Location & Boundary Invariance:
   - Start, middle, end, adjacent carriers, carrier adjacent to whitespace
6. Sentinel Privacy Invariant:
   - Generative body content never leaks into metadata or inspection reports
7. Zero Network Invariant:
   - Property tests run with zero socket activity
"""

from __future__ import annotations

import hashlib
import random
import socket
import unicodedata
from typing import List, Tuple
import pytest

from service.scripts.text_unicode import clean_text
from service.scripts.pipeline import Pipeline
from service.scripts.pipeline_types import DetectionStatus, PipelineStatus, ProcessingMode


def strip_invisible_markers(text: str) -> tuple[str, list[str]]:
    cleaned, stats = clean_text(text, normalize_spaces=False)
    removed_items = []
    for k, cnt in stats.get("removed", {}).items():
        removed_items.extend([k] * cnt)
    return cleaned, removed_items


class DeterministicUnicodePropertyGenerator:
    """Deterministic, reproducible seeded generator for Unicode property testing (Section 20 & 21)."""

    SEED = 0xDEADBEEF

    # Supported removable carrier codepoints in default mode
    DEFAULT_CARRIER_CODEPOINTS = [
        "\u200B",  # ZERO WIDTH SPACE
        "\uFEFF",  # ZERO WIDTH NO-BREAK SPACE (BOM)
        "\u00AD",  # SOFT HYPHEN
        "\U000E0001",  # UNICODE TAG BEGIN
        "\U000E0020",  # UNICODE TAG SPACE
        "\U000E0041",  # UNICODE TAG 'A'
        "\U000E007F",  # UNICODE TAG CANCEL
    ]

    # Additional carriers when strip_bidi=True
    BIDI_CARRIER_CODEPOINTS = [
        "\u200E",  # LEFT-TO-RIGHT MARK
        "\u200F",  # RIGHT-TO-LEFT MARK
    ]

    # Legitimate contextual Unicode that must NEVER be corrupted
    LEGITIMATE_CONTEXTUAL_FRAGMENTS = [
        "Hello World",
        "The quick brown fox jumps over the lazy dog.",
        "Café au lait & résumé",
        "naïve façade",
        # Emoji ZWJ sequences
        "👨‍👩‍👧‍👦",
        "🏳️‍🌈",
        "👩‍💻",
        "🏃🏽‍♀️",
        # Arabic text with cursive joiners
        "العربية لغة جميلة",
        "السلام عليكم ورحمة الله",
        "مكتبة الإسكندرية",
        # Devanagari text with conjuncts
        "नमस्ते भारत",
        "विद्या ददाति विनयं",
        "क्षेत्रीय सहयोग",
        # Non-breaking spaces
        "100\u00A0km/h",
        "Section\u202F4.2",
        "p.\u00A015",
        # Mixed scripts
        "Python 3.12 (CPython, 64-bit) — العربية / हिन्दी",
    ]

    def __init__(self, seed: int = SEED) -> None:
        self.rng = random.Random(seed)

    def generate_random_clean_string(self, max_length: int = 40) -> str:
        """Generate a clean string with no removable carriers."""
        length = self.rng.randint(0, max_length)
        if length == 0:
            return ""
        pool = self.LEGITIMATE_CONTEXTUAL_FRAGMENTS
        base = self.rng.choice(pool)
        if len(base) <= length:
            return base
        start = self.rng.randint(0, len(base) - length)
        return base[start : start + length]

    def inject_carriers(
        self,
        clean_text: str,
        count: int = 1,
        placement: str = "random",
    ) -> str:
        """Inject supported carrier codepoints into a clean text at specified placement."""
        if count <= 0:
            return clean_text

        chars = list(clean_text)
        carriers = [self.rng.choice(self.DEFAULT_CARRIER_CODEPOINTS) for _ in range(count)]

        if placement == "start":
            return "".join(carriers) + clean_text
        elif placement == "end":
            return clean_text + "".join(carriers)
        elif placement == "adjacent":
            idx = self.rng.randint(0, len(chars)) if chars else 0
            chars.insert(idx, "".join(carriers))
            return "".join(chars)
        elif placement == "adjacent_whitespace":
            # inject next to an existing whitespace or insert space + carrier
            ws_indices = [i for i, c in enumerate(chars) if c.isspace()]
            if ws_indices:
                target = self.rng.choice(ws_indices)
                chars.insert(target + 1, "".join(carriers))
                return "".join(chars)
            else:
                return clean_text + " " + "".join(carriers)
        else:  # random distributed
            for c in carriers:
                pos = self.rng.randint(0, len(chars)) if chars else 0
                chars.insert(pos, c)
            return "".join(chars)

    def generate_corpus(self, num_samples: int = 100) -> List[Tuple[str, str, str]]:
        """Generate a diverse corpus of (clean_text, carrier_text, category) samples."""
        corpus = []

        # 1. Edge cases
        corpus.append(("", "", "empty_string"))
        corpus.append(("A", "A", "single_ascii"))
        corpus.append(("é", "é", "single_latin_accent"))
        corpus.append(("", self.rng.choice(self.DEFAULT_CARRIER_CODEPOINTS), "carrier_only_single"))
        corpus.append(
            ("", "".join(self.rng.choices(self.DEFAULT_CARRIER_CODEPOINTS, k=5)), "carrier_only_multiple")
        )

        # 2. Legitimate contexts untouched
        for frag in self.LEGITIMATE_CONTEXTUAL_FRAGMENTS:
            corpus.append((frag, frag, "legitimate_context_clean"))

        # 3. NFC vs NFD forms
        nfc_sample = unicodedata.normalize("NFC", "Schöne Grüße aus München")
        nfd_sample = unicodedata.normalize("NFD", "Schöne Grüße aus München")
        corpus.append((nfc_sample, nfc_sample, "nfc_clean"))
        corpus.append((nfd_sample, nfd_sample, "nfd_clean"))

        # Injected carriers in NFC and NFD
        carrier = "\u200B"
        corpus.append((nfc_sample, self.inject_carriers(nfc_sample, 3, "random"), "nfc_with_carriers"))
        corpus.append((nfd_sample, self.inject_carriers(nfd_sample, 3, "random"), "nfd_with_carriers"))

        # 4. Placements (start, middle, end, adjacent, adjacent_whitespace)
        placements = ["start", "middle", "end", "adjacent", "adjacent_whitespace"]
        for i in range(num_samples - len(corpus)):
            base = self.generate_random_clean_string(max_length=50)
            if not base:
                base = "Sample text"
            placement = placements[i % len(placements)]
            k_carriers = (i % 4) + 1
            carrier_text = self.inject_carriers(base, count=k_carriers, placement=placement)
            corpus.append((base, carrier_text, f"generated_{placement}_{k_carriers}carriers"))

        return corpus


# Fixture for the property generator
@pytest.fixture(scope="module")
def unicode_generator() -> DeterministicUnicodePropertyGenerator:
    return DeterministicUnicodePropertyGenerator(seed=0xDEADBEEF)


# ==============================================================================
# Property Tests
# ==============================================================================


def test_property_already_clean_identity(unicode_generator):
    """Property 1: Clean text returns identical string and zero removed markers."""
    corpus = unicode_generator.generate_corpus(num_samples=60)
    for clean_text, _, category in corpus:
        if not clean_text:
            continue
        cleaned1, removed1 = strip_invisible_markers(clean_text)
        assert cleaned1 == clean_text, (
            f"Already-clean input failed identity in category {category}: {clean_text!r} -> {cleaned1!r}"
        )
        assert len(removed1) == 0, f"False positive removal on clean text: {removed1}"

        # Second pass must also be identical
        cleaned2, removed2 = strip_invisible_markers(cleaned1)
        assert cleaned2 == cleaned1
        assert len(removed2) == 0


def test_property_first_pass_byte_fixed_point(unicode_generator):
    """Property 2: Primary fixed-point property C(C(x)) == C(x)."""
    corpus = unicode_generator.generate_corpus(num_samples=100)
    for _, carrier_text, category in corpus:
        # First clean
        pass1_text, removed1 = strip_invisible_markers(carrier_text)
        pass1_bytes = pass1_text.encode("utf-8")
        sha1 = hashlib.sha256(pass1_bytes).hexdigest()

        # Second clean
        pass2_text, removed2 = strip_invisible_markers(pass1_text)
        pass2_bytes = pass2_text.encode("utf-8")
        sha2 = hashlib.sha256(pass2_bytes).hexdigest()

        # Property A: String & byte equality
        assert pass2_text == pass1_text, (
            f"Fixed-point string mismatch in category {category}: {pass1_text!r} != {pass2_text!r}"
        )
        assert pass2_bytes == pass1_bytes, (
            f"Fixed-point byte mismatch in category {category}"
        )

        # Property B: SHA256 invariant
        assert sha2 == sha1, f"SHA256 drift across clean passes in category {category}"

        # Property C: Size invariant
        assert len(pass2_bytes) == len(pass1_bytes)

        # Property D: Second pass removed count must be exactly 0
        assert len(removed2) == 0, (
            f"Second pass discovered residual carriers in category {category}: {removed2}"
        )


def test_property_legitimate_contextual_preservation(unicode_generator):
    """Property 3: Legitimate Unicode constructs must remain 100% exact."""
    for frag in unicode_generator.LEGITIMATE_CONTEXTUAL_FRAGMENTS:
        # Clean the fragment directly
        cleaned, removed = strip_invisible_markers(frag)
        assert cleaned == frag, f"Corrupted legitimate Unicode fragment: {frag!r} -> {cleaned!r}"
        assert len(removed) == 0

        # Inject carriers around the fragment
        injected = "\u200B" + frag + "\u200B"
        cleaned_injected, removed_injected = strip_invisible_markers(injected)
        assert cleaned_injected == frag, (
            f"Failed to restore exact legitimate Unicode after carrier removal: {cleaned_injected!r} != {frag!r}"
        )
        assert len(removed_injected) >= 2

        # Second pass on cleaned_injected
        pass2, removed2 = strip_invisible_markers(cleaned_injected)
        assert pass2 == frag
        assert len(removed2) == 0


def test_property_multi_carrier_one_pass_convergence(unicode_generator):
    """Property 4: All removable carrier codepoints removed in a single pass."""
    for carrier in unicode_generator.DEFAULT_CARRIER_CODEPOINTS:
        # Multiple occurrences in various patterns
        text = f"Start{carrier}middle{carrier}{carrier}end{carrier}"
        p1, r1 = strip_invisible_markers(text)
        assert carrier not in p1, f"Carrier {carrier!r} survived pass 1 in {text!r}"
        assert len(r1) == 4

        # Pass 2 must be no-op
        p2, r2 = strip_invisible_markers(p1)
        assert p2 == p1
        assert len(r2) == 0

    # Test bidi carriers when strip_bidi=True
    for carrier in unicode_generator.BIDI_CARRIER_CODEPOINTS:
        text = f"Start{carrier}middle{carrier}end"
        cleaned, stats = clean_text(text, normalize_spaces=False, strip_bidi=True)
        assert carrier not in cleaned
        assert stats["removed_count"] == 2


def test_property_pipeline_text_idempotence(unicode_generator):
    """Property 5: Pipeline text cleaning achieves byte fixed point with NO_CHANGE_REQUIRED."""
    pipeline = Pipeline()
    corpus = unicode_generator.generate_corpus(num_samples=40)

    for clean_text, carrier_text, category in corpus:
        in_bytes = carrier_text.encode("utf-8")

        # First clean
        b1, rep1 = pipeline.clean(in_bytes, filename="test.txt", mode=ProcessingMode.SAFE)
        sha1 = hashlib.sha256(b1).hexdigest()

        # Second clean
        b2, rep2 = pipeline.clean(b1, filename="test.txt", mode=ProcessingMode.SAFE)
        sha2 = hashlib.sha256(b2).hexdigest()

        # Idempotence assertions
        assert b2 == b1, f"Pipeline text byte mismatch in category {category}"
        assert sha2 == sha1
        assert len(b2) == len(b1)
        assert rep2.status == PipelineStatus.NO_CHANGE_REQUIRED, (
            f"Expected NO_CHANGE_REQUIRED on pass 2, got {rep2.status.value} in category {category}"
        )
        assert rep2.output.changed is False
        assert rep2.output.would_change is False
        assert len(rep2.mutation_plan.mutations) == 0, (
            f"Expected empty mutation plan on pass 2, got {rep2.mutation_plan.mutations} in {category}"
        )


def test_property_report_privacy_sentinel(unicode_generator):
    """Property 6: Random body text sentinel never appears in serialized reports."""
    import json

    pipeline = Pipeline()
    sentinel = f"SECRET_SENTINEL_{unicode_generator.rng.randint(100000, 999999)}_DATA"
    body_text = f"Confidential Document: {sentinel} \u200B with watermark."

    b1, rep1 = pipeline.clean(body_text.encode("utf-8"), filename="test.txt")
    rep1_json = json.dumps(rep1.to_dict())

    assert sentinel not in rep1_json, "Privacy violation: body text sentinel leaked into CleaningReport JSON!"

    # Second pass
    b2, rep2 = pipeline.clean(b1, filename="test.txt")
    rep2_json = json.dumps(rep2.to_dict())
    assert sentinel not in rep2_json


def test_property_zero_network_isolation(monkeypatch, unicode_generator):
    """Property 7: Zero network calls made during property testing."""
    def _forbidden_socket(*args, **kwargs):
        raise AssertionError("Network socket activity detected during property test!")

    monkeypatch.setattr(socket, "socket", _forbidden_socket)
    if hasattr(socket, "create_connection"):
        monkeypatch.setattr(socket, "create_connection", _forbidden_socket)

    pipeline = Pipeline()
    sample = "Network Isolation Test \u200B with joiners: 👨‍👩‍👧‍👦"
    b1, rep1 = pipeline.clean(sample.encode("utf-8"), filename="test.txt")
    b2, rep2 = pipeline.clean(b1, filename="test.txt")

    assert b2 == b1
    assert rep2.status == PipelineStatus.NO_CHANGE_REQUIRED
