#!/usr/bin/env python3
"""HTTP service exposing the watermarks-remover cleaning pipeline.

Stdlib-only. The agent skill and any web app can call it over HTTP instead of
running the CLI scripts locally.

Endpoints:
    GET  /health         -> {"ok": true, "version": ...}
    GET  /capabilities   -> which optional tools / pixel backends are present
    GET  /openapi.json   -> dynamically generated OpenAPI 3.0.3 spec
    POST /inspect        -> {"file": <base64>, "name": "x.png"} -> findings JSON
    POST /detect         -> {"file": <base64>, "name": "x.txt"} -> watermark detector reports
    POST /clean          -> {"file": <base64>, "name": "x.png", "options": {...}}
                         -> {"cleaned": <base64>, "report": {...}}
    POST /watermark      -> {"text": str, "keys": list[int], "options": {...}}
                         -> {"ok": true, "kind": "text", "watermarked_text": str, "report": {...}}
    POST /inspect/batch  -> {"files": [{"file": <base64>, "name": "x.png"}, ...]}
                         -> {"results": [{"name", "ok", "kind", "report", "suspicious"}, ...]}
    POST /detect/batch   -> {"files": [{"file": <base64>, "name": "x.txt"}, ...]}
                         -> {"results": [{"name", "ok", "kind", "detections", "report"}, ...]}
    POST /clean/batch    -> {"files": [{"file": <base64>, "name": "x.png", "options": {...}}, ...]}
                         -> {"results": [{"name", "ok", "kind", "cleaned", "report"}, ...]}
    POST /watermark/batch -> {"files": [{"text": str, "keys": list[int], ...}, ...]}
                         -> {"results": [{"name", "ok", "kind", "watermarked_text", "report"}, ...]}

Batch endpoints loop the same single-file pipeline as /inspect, /detect, /clean, and /watermark; a
per-file failure (unknown format, oversized name, bad option) shows up as
that entry's "ok": false with an "error" string and never aborts the rest of
the batch. Capped at WATERMARKS_MAX_BATCH_FILES entries per request (default
50) — the existing MAX_BODY_BYTES envelope cap still bounds total payload
size the same as a single-file request.

Hardening mirrors the CLIs: input size caps, binary-as-text guard, atomic
writes, loopback-only bind by default, optional bearer API key. Run it as an
unprivileged user (the Docker image does). Intended for a trusted network;
expose through a reverse proxy if reachable from untrusted clients.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
from datetime import datetime
from functools import cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from av_meta import clean_av, inspect_av
from clean_audio import audio_purify, is_audio_format, is_audio_name, media_has_video
from clean_video import video_purify
from common import (
    MAX_INPUT_BYTES,
    eprint,
    looks_binary,
    subprocess_creationflags,
    subprocess_preexec_fn,
    which,
)
from container_meta import (
    CLEAN_ATTACHMENT_MODES,
    DEEP_IMAGE_MODES,
    DEFAULT_CLEAN_ATTACHMENTS,
    clean_container,
    inspect_container,
)
from format_dispatch import classify_bytes
from image_meta import clean_image, inspect_image, run_synthid_score, synthid_is_watermarked
from score_stylometry import score_text_stylometry
from text_detectors import detector_status, run_all_text_detectors, run_text_detectors
from text_unicode import clean_text, inspect_text
from text_watermark import (
    generate_watermark_text,
    parse_watermark_options,
    resolve_timeout,
)

import hashlib
from format_policy import FormatPolicyRegistry
from pipeline import Pipeline
from pipeline_types import (
    CleaningReport,
    DetectionStatus,
    ErrorCode,
    PipelineStatus,
    ProcessingMode,
)

VERSION = os.environ.get("WATERMARKS_SERVER_VERSION", "dev")

# Optional bearer token: when set, every request must send
# `Authorization: Bearer <key>`. Empty means no auth (default).
API_KEY = os.environ.get("WATERMARKS_SERVER_API_KEY", "").strip()

# Body cap for the JSON envelope. Base64 inflates by 4/3, so the decoded file
# stays well under MAX_INPUT_BYTES for the same cap.
MAX_BODY_BYTES = MAX_INPUT_BYTES + (MAX_INPUT_BYTES >> 1)

# Per-request file count cap for /inspect/batch and /clean/batch. MAX_BODY_BYTES
# already bounds total payload size; this bounds worst-case CPU/thread time from
# a request packing many tiny files into one call.
MAX_BATCH_FILES = int(os.environ.get("WATERMARKS_MAX_BATCH_FILES", "50"))

ALLOWED_CLEAN_OPTIONS = {
    "nfkc": bool,
    "aggressive_homoglyphs": bool,
    "normalize_spaces": bool,
    "keep_non_ai_metadata": bool,
    "also_layer_a_text": bool,
    "remove_pixel": str,
    "remove_audio_watermark": bool,
    "strip_all_metadata": bool,
    "detect_before": bool,
    "detect_after": bool,
    "deep_images": str,
    "clean_attachments": str,
    "style": str,
    "strategy": str,
    "mode": str,
    "dry_run": bool,
}

# Default Layer B strategy loaded from the strategy config file (overridable by
# env/CLI). None means no Layer B rewrite on text.
_DEFAULT_STRATEGY: str | None = None


def error_code_to_http_status(error_code: Any) -> HTTPStatus:
    """Map pipeline ErrorCode to standard HTTP status codes (Section 12)."""
    if error_code is None:
        return HTTPStatus.INTERNAL_SERVER_ERROR
    val = error_code.value if hasattr(error_code, "value") else str(error_code)
    mapping = {
        "UNSUPPORTED_FORMAT": HTTPStatus.UNSUPPORTED_MEDIA_TYPE,          # 415
        "INVALID_CONTAINER": HTTPStatus.BAD_REQUEST,                      # 400
        "VALIDATION_FAILED": HTTPStatus.UNPROCESSABLE_ENTITY,             # 422
        "OPTIONAL_DEPENDENCY_MISSING": HTTPStatus.FAILED_DEPENDENCY,      # 424
        "UNSUPPORTED_ARCHIVE_FEATURE": HTTPStatus.UNPROCESSABLE_ENTITY,   # 422
        "PROCESSING_LIMIT_EXCEEDED": HTTPStatus.REQUEST_ENTITY_TOO_LARGE, # 413
        "INTERNAL_ERROR": HTTPStatus.INTERNAL_SERVER_ERROR,              # 500
    }
    return mapping.get(val, HTTPStatus.INTERNAL_SERVER_ERROR)


@cache
def _ghostscript_usable() -> bool:
    """True when a Ghostscript binary is present and runnable.

    Cached and guarded like _tool_usable: /capabilities is polled, and probing
    spawns a process every time otherwise.
    """
    from container_meta import which_ghostscript

    gs = which_ghostscript()
    if not gs:
        return False
    try:
        r = subprocess.run(
            [gs, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            preexec_fn=subprocess_preexec_fn,
            creationflags=subprocess_creationflags,
        )
        return r.returncode == 0
    except Exception:
        return False


def _json_ok(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


# Flag that makes each tool print its version and exit 0. They disagree:
# exiftool treats `--version` as an unknown option and prints usage instead.
_VERSION_FLAG = {
    "c2patool": "--version",
    "exiftool": "-ver",
    "qpdf": "--version",
    # ffmpeg has no --version; it exits 8 and the probe read that as unusable.
    "ffmpeg": "-version",
}


@cache
def _tool_usable(cmd: str) -> bool:
    """True only when the tool is on PATH *and* can actually execute.

    `which` alone answers the wrong question. A binary built for another
    architecture sits on PATH and still dies before main() -- the published
    image pins a multi-arch base digest, so an arm64 host gets an arm64 image
    carrying the x86_64-only c2patool release. Advertising that as available
    is what lets a probe which never ran read as a clean verdict downstream.

    Cached: a container's tool set cannot change while the process lives.
    """
    path = which(cmd)
    if not path:
        return False
    try:
        r = subprocess.run(
            [path, _VERSION_FLAG.get(cmd, "--version")],
            capture_output=True,
            text=True,
            timeout=10,
            preexec_fn=subprocess_preexec_fn,
            check=False,
            creationflags=subprocess_creationflags,
        )
    except Exception:
        return False
    return r.returncode == 0


def capabilities() -> dict[str, Any]:
    reg = FormatPolicyRegistry.get_default()
    formats_dict = {}
    for p in reg.all_policies():
        formats_dict[p.format_name] = {
            "format": p.format_name,
            "extensions": list(p.extensions),
            "inspect_capabilities": list(p.inspect_capabilities),
            "clean_capabilities": list(p.clean_capabilities),
            "fidelity_levels": [f.value for f in p.fidelity_requirements],
            "optional_dependencies": list(p.optional_dependencies),
            "network_policy": p.network_policy,
            "supported_modes": list(p.supported_modes),
            "destructive_operations": list(p.destructive_operations),
            "verify_capabilities": list(p.verify_capabilities),
        }

    return {
        "version": VERSION,
        "source": "service/scripts/format_policy.py",
        "formats": formats_dict,
        "tools": {
            "c2patool": _tool_usable("c2patool"),
            "exiftool": _tool_usable("exiftool"),
            "qpdf": _tool_usable("qpdf"),
            "ghostscript": _ghostscript_usable(),
            "ffmpeg": _tool_usable("ffmpeg"),
        },
        "pixel_backends": {
            "ctrlregen": bool(os.environ.get("NOAI_WATERMARK_DIR")),
            "diffusion": bool(os.environ.get("MARKDIFFUSION_DIR")),
        },
        "scorers": {
            "synthid": bool(os.environ.get("REVERSE_SYNTHID_DIR")),
            "synthid_http": bool(os.environ.get("WATERMARKS_SYNTHID_SCORER_URL")),
            "stylometry": True,
        },
        "text_detectors": detector_status(),
        "text_generators": {
            "synthid_http": bool(os.environ.get("WATERMARKS_SYNTHID_TEXT_URL")),
            "markllm": bool(os.environ.get("MARKLLM_DIR")),
        },
        "harnesses": {
            "markllm": bool(os.environ.get("MARKLLM_DIR")),
        },
    }


# OpenAPI generation. The spec is built from this single declarative table
# plus live runtime values (version, auth, allowed options), so it can never
# drift from the endpoints the handler actually serves. Served at /openapi.json.


def _schema(**props: Any) -> dict[str, Any]:
    return props


# Plain-language meaning of each evidence class, keyed by class name. Shared by
# the OpenAPI schema and the runtime payload so the two never drift.
_SUSPICIOUS_CLASS_DESCRIPTIONS = {
    "provenance": (
        "Observable, deterministic provenance metadata (C2PA/Content Credentials "
        "or AI-metadata markers) embedded in the file. Strongest evidence class: "
        "directly inspectable, not inferred."
    ),
    "layer_a_unicode": (
        "Invisible/format Unicode carriers (Layer A) detected in the text body. "
        "Deterministic but edit-based: a known carrier was present, not proof of "
        "AI authorship."
    ),
    "watermark_detector": (
        "A positive result from a detector configured for a specific watermark "
        "scheme. Strong only for that scheme; it is not evidence of any other mark."
    ),
    "stylometry": (
        "Stylometric AI-density score reached the threshold. Heuristic and "
        "statistical: weaker than observable metadata and subject to false positives."
    ),
}


def _suspicious_schema() -> dict[str, Any]:
    """OpenAPI schema for the structured `suspicious` evidence object."""

    def cls(name: str, strength: str, signals: dict[str, Any]) -> dict[str, Any]:
        """Build the schema for one evidence class."""
        return _schema(
            type="object",
            properties={
                "present": _schema(type="boolean"),
                "strength": _schema(type="string", description=strength),
                "description": _schema(
                    type="string", description=_SUSPICIOUS_CLASS_DESCRIPTIONS[name]
                ),
                "signals": _schema(type="object", properties=signals),
            },
        )

    return _schema(
        type="object",
        description=(
            "Heterogeneous evidence for suspected marking, reported per evidence "
            "class so callers can weigh each signal instead of trusting one boolean. "
            "Not a single provenance judgment."
        ),
        properties={
            "verdict": _schema(type="boolean"),
            "description": _schema(type="string"),
            "classes": _schema(
                type="object",
                properties={
                    "provenance": cls(
                        "provenance",
                        "definitive",
                        {
                            "has_c2pa": _schema(type="boolean"),
                            "has_ai_metadata": _schema(type="boolean"),
                        },
                    ),
                    "layer_a_unicode": cls(
                        "layer_a_unicode",
                        "deterministic",
                        {"suspicious_total": _schema(type="integer")},
                    ),
                    "watermark_detector": cls(
                        "watermark_detector",
                        "scheme_specific",
                        {
                            "detected_any": _schema(type="boolean"),
                            "detectors": _schema(type="array", items=_schema(type="object")),
                        },
                    ),
                    "stylometry": cls(
                        "stylometry",
                        "heuristic",
                        {
                            # Non-text assets have no stylometry, so these are null.
                            "score": _schema(type="number", nullable=True),
                            "density_tier": _schema(type="string", nullable=True),
                        },
                    ),
                },
            ),
        },
    )


def _file_request(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "required": ["file"],
        "properties": {
            "file": {
                "type": "string",
                "description": "Base64-encoded file bytes",
                "example": "SGVsbG8gd29ybGQ=",
            },
            "name": {
                "type": "string",
                "description": "Original filename (extension drives format routing)",
                "example": "notes.md",
            },
        },
    }
    if extra:
        schema["properties"].update(extra["properties"])
        schema["required"] = schema["required"] + extra.get("required", [])
    return schema


def _clean_request_schema() -> dict[str, Any]:
    options: dict[str, Any] = {}
    for key, kind in ALLOWED_CLEAN_OPTIONS.items():
        if kind is bool:
            options[key] = _schema(type="boolean")
        else:
            options[key] = _schema(type="string")
    return _file_request(
        {
            "properties": {
                "options": _schema(type="object", properties=options, additionalProperties=False)
            },
        }
    )


def _watermark_error_status(res: dict[str, Any]) -> HTTPStatus:
    """Map a watermark failure result to the correct HTTP status.

    Uses the stable ``error_code`` field returned by the text_watermark
    client rather than fragile substring-matching on the human-readable
    ``error`` message.
    """
    _ERROR_CODE_MAP: dict[str, HTTPStatus] = {
        "unconfigured": HTTPStatus.SERVICE_UNAVAILABLE,
        "auth": HTTPStatus.BAD_GATEWAY,
        "client_error": HTTPStatus.BAD_REQUEST,
        "unreachable": HTTPStatus.BAD_GATEWAY,
        "backend_error": HTTPStatus.BAD_GATEWAY,
        "timeout": HTTPStatus.BAD_GATEWAY,
        "ssrf": HTTPStatus.BAD_GATEWAY,
    }
    code = res.get("error_code", "")
    if code in _ERROR_CODE_MAP:
        return _ERROR_CODE_MAP[code]
    # Fallback for any result that pre-dates the error_code field.
    return HTTPStatus.BAD_REQUEST


def _watermark_request_schema() -> dict[str, Any]:
    return _schema(
        type="object",
        additionalProperties=False,
        properties={
            "text": _schema(type="string", description="Prompt or text to watermark"),
            "file": _schema(type="string", description="Base64-encoded text file"),
            "name": _schema(type="string", description="Optional filename"),
            "keys": _schema(
                type="array",
                items=_schema(type="integer"),
                description="Optional SynthID key sequence",
            ),
            "options": _schema(
                type="object",
                additionalProperties=False,
                properties={
                    "scheme": _schema(type="string", default="synthid"),
                    "seed": _schema(type="integer"),
                    "max_new_tokens": _schema(
                        type="integer",
                        default=200,
                        minimum=1,
                        maximum=8192,
                    ),
                    "min_length": _schema(
                        type="integer",
                        default=0,
                        minimum=0,
                        maximum=8192,
                    ),
                    "temperature": _schema(
                        type="number",
                        minimum=0,
                        exclusiveMinimum=True,
                    ),
                    "top_p": _schema(
                        type="number",
                        minimum=0,
                        exclusiveMinimum=True,
                        maximum=1,
                    ),
                    "model": _schema(type="string"),
                    "device": _schema(
                        type="string",
                        description="Inference device (e.g. 'cpu', 'cuda', 'cuda:0')",
                    ),
                    "config": _schema(
                        type="string",
                        description="Path to a custom watermark config file",
                    ),
                    "offline": _schema(
                        type="boolean",
                        default=False,
                        description="If true, disable network access for model loading",
                    ),
                },
            ),
        },
    )


_ERROR_SCHEMA = _schema(
    type="object",
    properties={"ok": _schema(type="boolean", enum=[False]), "error": _schema(type="string")},
)

_OPENAPI_PATHS: dict[str, dict[str, Any]] = {
    "/health": {
        "get": {
            "summary": "Liveness and version",
            "responses": {
                "200": _schema(
                    type="object",
                    properties={"ok": _schema(type="boolean"), "version": _schema(type="string")},
                )
            },
        }
    },
    "/capabilities": {
        "get": {
            "summary": "Which optional tools and heavy backends are available",
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "version": _schema(type="string"),
                        "tools": _schema(
                            type="object",
                            properties={
                                k: _schema(type="boolean")
                                for k in ("c2patool", "exiftool", "qpdf", "ghostscript", "ffmpeg")
                            },
                        ),
                        "pixel_backends": _schema(
                            type="object",
                            properties={
                                k: _schema(type="boolean") for k in ("ctrlregen", "diffusion")
                            },
                        ),
                        "scorers": _schema(
                            type="object",
                            properties={
                                "synthid": _schema(type="boolean"),
                                "synthid_http": _schema(type="boolean"),
                                "stylometry": _schema(type="boolean"),
                            },
                        ),
                        "harnesses": _schema(
                            type="object", properties={"markllm": _schema(type="boolean")}
                        ),
                        "text_detectors": _schema(
                            type="object",
                            additionalProperties=_schema(type="boolean"),
                        ),
                        "text_generators": _schema(
                            type="object",
                            properties={
                                "synthid_http": _schema(type="boolean"),
                                "markllm": _schema(type="boolean"),
                            },
                        ),
                    },
                )
            },
        }
    },
    "/openapi.json": {
        "get": {
            "summary": "This OpenAPI 3.0.3 document, generated dynamically",
            "responses": {
                "200": _schema(type="object", description="An OpenAPI 3.0.3 document"),
            },
        }
    },
    "/inspect": {
        "post": {
            "summary": "Inspect a file for AI provenance marks (text / image / container auto-routed)",
            "requestBody": _schema(
                required=True,
                content={
                    "application/json": _schema(
                        schema=_file_request(
                            {
                                "properties": {
                                    "detect": _schema(
                                        type="boolean",
                                        description=(
                                            "Also run configured text watermark detectors "
                                            "(opt-in; may call vendor APIs and send text "
                                            "to them)"
                                        ),
                                    )
                                },
                                "required": [],
                            }
                        )
                    )
                },
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "kind": _schema(type="string", enum=["text", "image", "container", "av"]),
                        "suspicious": _suspicious_schema(),
                        "report": _schema(type="object"),
                    },
                )
            },
        }
    },
    "/clean": {
        "post": {
            "summary": "Clean a file; returns the cleaned bytes and an actions/stats report",
            "requestBody": _schema(
                required=True,
                content={"application/json": _schema(schema=_clean_request_schema())},
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "kind": _schema(type="string", enum=["text", "image", "container", "av"]),
                        "cleaned": _schema(
                            type="string", description="Base64-encoded cleaned file bytes"
                        ),
                        "report": _schema(type="object"),
                    },
                )
            },
        }
    },
    "/verify": {
        "post": {
            "summary": "Verify document fidelity between original and candidate files",
            "requestBody": _schema(
                required=True,
                content={
                    "application/json": _schema(
                        type="object",
                        required=["original", "candidate"],
                        properties={
                            "original": _schema(type="string", description="Base64-encoded original bytes"),
                            "candidate": _schema(type="string", description="Base64-encoded candidate bytes"),
                            "name": _schema(type="string", description="Optional filename"),
                        },
                    )
                },
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "status": _schema(type="string"),
                        "format": _schema(type="string"),
                        "validation": _schema(type="object"),
                        "invariants": _schema(type="array", items=_schema(type="string")),
                        "warnings": _schema(type="array", items=_schema(type="string")),
                        "hashes": _schema(type="object"),
                    },
                ),
                "422": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "status": _schema(type="string"),
                        "error": _schema(type="string"),
                    },
                ),
            },
        }
    },
    "/detect": {
        "post": {
            "summary": "Run watermark detectors on a file (text: vendor/statistical; image: SynthID score)",
            "requestBody": _schema(
                required=True,
                content={"application/json": _schema(schema=_file_request())},
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "kind": _schema(type="string", enum=["text", "image", "container", "av"]),
                        "detections": _schema(type="array", items=_schema(type="object")),
                    },
                )
            },
        }
    },
    "/inspect/batch": {
        "post": {
            "summary": f"Inspect up to {MAX_BATCH_FILES} files in one request",
            "requestBody": _schema(
                required=True,
                content={
                    "application/json": _schema(
                        schema=_schema(
                            type="object",
                            required=["files"],
                            properties={"files": _schema(type="array", items=_file_request())},
                        )
                    )
                },
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "results": _schema(
                            type="array",
                            items=_schema(
                                type="object",
                                properties={
                                    "name": _schema(type="string"),
                                    "ok": _schema(type="boolean"),
                                    "kind": _schema(
                                        type="string",
                                        enum=["text", "image", "container", "av", "unknown"],
                                    ),
                                    "suspicious": _suspicious_schema(),
                                    "report": _schema(type="object"),
                                    "error": _schema(type="string"),
                                },
                            ),
                        ),
                    },
                )
            },
        }
    },
    "/detect/batch": {
        "post": {
            "summary": f"Run watermark detectors on up to {MAX_BATCH_FILES} files in one request",
            "requestBody": _schema(
                required=True,
                content={
                    "application/json": _schema(
                        schema=_schema(
                            type="object",
                            required=["files"],
                            properties={"files": _schema(type="array", items=_file_request())},
                        )
                    )
                },
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "results": _schema(
                            type="array",
                            items=_schema(
                                type="object",
                                properties={
                                    "name": _schema(type="string"),
                                    "ok": _schema(type="boolean"),
                                    "kind": _schema(
                                        type="string",
                                        enum=["text", "image", "container", "av"],
                                    ),
                                    "detections": _schema(
                                        type="array", items=_schema(type="object")
                                    ),
                                    "report": _schema(type="object"),
                                    "error": _schema(type="string"),
                                },
                            ),
                        ),
                    },
                )
            },
        }
    },
    "/clean/batch": {
        "post": {
            "summary": f"Clean up to {MAX_BATCH_FILES} files in one request",
            "requestBody": _schema(
                required=True,
                content={
                    "application/json": _schema(
                        schema=_schema(
                            type="object",
                            required=["files"],
                            properties={
                                "files": _schema(type="array", items=_clean_request_schema())
                            },
                        )
                    )
                },
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "results": _schema(
                            type="array",
                            items=_schema(
                                type="object",
                                properties={
                                    "name": _schema(type="string"),
                                    "ok": _schema(type="boolean"),
                                    "kind": _schema(
                                        type="string", enum=["text", "image", "container", "av"]
                                    ),
                                    "cleaned": _schema(type="string"),
                                    "report": _schema(type="object"),
                                    "error": _schema(type="string"),
                                },
                            ),
                        ),
                    },
                )
            },
        }
    },
    "/watermark": {
        "post": {
            "summary": "Generate watermarked text using the configured sidecar or generator",
            "requestBody": _schema(
                required=True,
                content={"application/json": _schema(schema=_watermark_request_schema())},
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "kind": _schema(type="string", enum=["text"]),
                        "watermarked_text": _schema(type="string"),
                        "report": _schema(type="object"),
                    },
                ),
                "502": {
                    "description": "Sidecar / MarkLLM backend error",
                    "content": {"application/json": {"schema": _ERROR_SCHEMA}},
                },
                "503": {
                    "description": "No text watermark generator configured",
                    "content": {"application/json": {"schema": _ERROR_SCHEMA}},
                },
            },
        }
    },
    "/watermark/batch": {
        "post": {
            "summary": f"Generate watermarked text for up to {MAX_BATCH_FILES} files in one request",
            "requestBody": _schema(
                required=True,
                content={
                    "application/json": _schema(
                        schema=_schema(
                            type="object",
                            required=["files"],
                            properties={
                                "files": _schema(
                                    type="array",
                                    items=_watermark_request_schema(),
                                )
                            },
                        )
                    )
                },
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "results": _schema(
                            type="array",
                            items=_schema(
                                type="object",
                                properties={
                                    "name": _schema(type="string"),
                                    "ok": _schema(type="boolean"),
                                    "kind": _schema(type="string", enum=["text"]),
                                    "watermarked_text": _schema(type="string"),
                                    "report": _schema(type="object"),
                                    "error": _schema(type="string"),
                                },
                            ),
                        ),
                    },
                )
            },
        }
    },
    "/batch": {
        "post": {
            "summary": f"Process a batch of up to {MAX_BATCH_FILES} files with per-file failure isolation",
            "requestBody": _schema(
                required=True,
                content={
                    "application/json": _schema(
                        schema=_schema(
                            type="object",
                            required=["files"],
                            properties={
                                "files": _schema(type="array", items=_file_request()),
                                "mode": _schema(type="string", enum=["safe", "balanced", "aggressive"]),
                                "dry_run": _schema(type="boolean"),
                                "operation": _schema(type="string", enum=["clean", "inspect"]),
                            },
                        )
                    )
                },
            ),
            "responses": {
                "200": _schema(
                    type="object",
                    properties={
                        "ok": _schema(type="boolean"),
                        "report": _schema(type="object"),
                        "outputs_included": _schema(type="boolean"),
                        "output_delivery": _schema(type="string"),
                        "outputs": _schema(type="array", items=_schema(type="object")),
                    },
                )
            },
        }
    },
}

_COMMON_ERRORS = {
    "400": {
        "description": "Bad request",
        "content": {"application/json": {"schema": _ERROR_SCHEMA}},
    },
    "401": {
        "description": "Missing/invalid bearer token",
        "content": {"application/json": {"schema": _ERROR_SCHEMA}},
    },
    "404": {"description": "Not found", "content": {"application/json": {"schema": _ERROR_SCHEMA}}},
    "413": {
        "description": "Request body too large",
        "content": {"application/json": {"schema": _ERROR_SCHEMA}},
    },
    "500": {
        "description": "Internal error",
        "content": {"application/json": {"schema": _ERROR_SCHEMA}},
    },
}


def openapi_spec() -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for path, ops in _OPENAPI_PATHS.items():
        for method, op in ops.items():
            responses = dict(_COMMON_ERRORS)
            for status, body in op["responses"].items():
                if "description" in body and "content" in body:
                    responses[status] = body
                    continue
                responses[status] = {
                    "description": "Success",
                    "content": {"application/json": {"schema": body}},
                }
            paths.setdefault(path, {})[method] = {
                "summary": op["summary"],
                "responses": responses,
                **((op.get("requestBody") and {"requestBody": op["requestBody"]}) or {}),
            }

    spec: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": "watermarks-remover service",
            "version": VERSION,
            "description": "Strip multi-vendor AI provenance marks (Unicode, C2PA/EXIF/XMP, containers). "
            "Files are passed base64-encoded in JSON; cleaned bytes come back base64-encoded.",
        },
        "paths": paths,
    }
    if API_KEY:
        spec["components"] = {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"},
            }
        }
        spec["security"] = [{"bearerAuth": []}]
    return spec


def _safe_name(name: str) -> str:
    """Reduce a client-supplied filename to a bare basename safe for temp use.

    CodeQL (uncontrolled data in path expression): a name like '../../x'
    would otherwise let the write below escape the request temp dir. Fold
    Windows separators too, and fall back to a neutral name for '.', '..' or
    empty results.
    """
    base = Path(name.replace("\\", "/")).name
    if base in ("", ".", ".."):
        return "input"
    return base


def _tmp_path(tmpdir: Path, *parts: str) -> Path:
    """Join *parts* under *tmpdir* and refuse anything that escapes it.

    Defense-in-depth for the CodeQL "uncontrolled data in path expression"
    findings: even if a caller slips a separator through, the write can never
    land outside the request temp dir.
    """
    path = tmpdir.joinpath(*parts)
    if path.parent != tmpdir:
        raise ValueError("unsafe filename")
    return path


def _decode_input(body: dict[str, Any]) -> tuple[bytes, str]:
    raw = body.get("file")
    if not isinstance(raw, str):
        raise ValueError("missing string field 'file' (base64-encoded bytes)")
    name = body.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError("'name' must be a string")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("'file' is not valid base64") from None
    return data, _safe_name(name or "")


def _parse_clean_options(options: Any) -> dict[str, Any]:
    if options is None:
        return {}
    if not isinstance(options, dict):
        raise ValueError("'options' must be an object")
    for key, value in options.items():
        if key not in ALLOWED_CLEAN_OPTIONS:
            raise ValueError(f"unknown option: {key}")
        expected_type = ALLOWED_CLEAN_OPTIONS[key]
        if not isinstance(value, expected_type):
            type_name = "boolean" if expected_type is bool else "string"
            raise ValueError(f"option {key!r} must be a {type_name}")
    # An unrecognised deep_images value used to fall back to "auto", which turns
    # a request for lossless cleaning into one that may recompress. Reject it
    # here, where every caller -- single file and batch alike -- passes through.
    deep_images = options.get("deep_images")
    if deep_images is not None and deep_images not in DEEP_IMAGE_MODES:
        raise ValueError(f"option 'deep_images' must be one of {sorted(DEEP_IMAGE_MODES)}")
    clean_attachments = options.get("clean_attachments")
    if clean_attachments is not None and clean_attachments not in CLEAN_ATTACHMENT_MODES:
        raise ValueError(
            f"option 'clean_attachments' must be one of {sorted(CLEAN_ATTACHMENT_MODES)}"
        )
    # A per-request strategy overrides the default; validate it up front so a bad
    # tactic/intensity is a 400 rather than a mid-clean failure.
    if "strategy" in options:
        from rewrite_text import parse_strategy

        parse_strategy(options["strategy"])
    return options


def _load_default_strategy(config_path: Path) -> str | None:
    """Read the default Layer B strategy from the config file.

    Returns None when the config file is absent (no Layer B on text). A file that
    is present but malformed (bad JSON, unknown tactic, bad intensity) is a
    startup error, since the config is explicit in-repo.
    """
    try:
        data = json.loads(config_path.read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        raise SystemExit(f"invalid strategy config {config_path}: {e}") from e
    spec = data.get("default_strategy")
    if spec is None:
        return None
    from rewrite_text import parse_strategy

    parse_strategy(spec)  # raises ValueError on a bad strategy
    return spec


def _apply_layer_b(text: str, strategy: str, options: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Apply a Layer B rewrite strategy to *text*, rejecting if unavailable.

    Raises ValueError for an unconfigured/unavailable backend or model so the
    caller surfaces a 400 rather than a 500. Wraps runtime failures the same way.
    """
    from rewrite_text import LLM_TACTICS, apply_strategy, parse_strategy

    steps = parse_strategy(strategy)
    needs_llm = any(t in LLM_TACTICS for t, _ in steps)
    backend = os.environ.get("WATERMARKS_REWRITE_BACKEND", "print-prompt")
    if needs_llm:
        if backend not in ("openai-compatible", "ollama"):
            raise ValueError(
                "Layer B strategy needs an LLM rewrite backend (WATERMARKS_REWRITE_BACKEND)"
            )
        needs_key = backend == "openai-compatible"
        missing = not os.environ.get("WATERMARKS_REWRITE_MODEL") or not os.environ.get(
            "WATERMARKS_REWRITE_BASE_URL"
        )
        if needs_key:
            missing = missing or not os.environ.get("WATERMARKS_REWRITE_API_KEY")
        if missing:
            required = "WATERMARKS_REWRITE_MODEL/BASE_URL"
            if needs_key:
                required += "/API_KEY"
            raise ValueError(f"Layer B strategy needs the rewrite backend configured ({required})")
    if any(t == "mlm" for t, _ in steps):
        import importlib.util

        if importlib.util.find_spec("transformers") is None:
            raise ValueError("Layer B 'mlm' step requires transformers")
    base_url = os.environ.get("WATERMARKS_REWRITE_BASE_URL")
    if needs_llm and base_url:
        host = urlparse(base_url).hostname or ""
        allow_remote = os.environ.get("WATERMARKS_REWRITE_ALLOW_REMOTE", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if host not in ("127.0.0.1", "localhost", "::1") and not allow_remote:
            raise ValueError(
                "Layer B strategy uses a remote rewrite endpoint; set "
                "WATERMARKS_REWRITE_ALLOW_REMOTE=1"
            )
    try:
        out, stats = apply_strategy(
            text,
            steps,
            backend=backend,
            model=os.environ.get("WATERMARKS_REWRITE_MODEL"),
            base_url=os.environ.get("WATERMARKS_REWRITE_BASE_URL"),
            api_key=os.environ.get("WATERMARKS_REWRITE_API_KEY"),
            temperature=float(os.environ.get("WATERMARKS_REWRITE_TEMPERATURE", "0.9")),
            reasoning_effort=(
                None
                if os.environ.get("WATERMARKS_REWRITE_REASONING_EFFORT") == "off"
                else os.environ.get("WATERMARKS_REWRITE_REASONING_EFFORT") or None
            ),
            style=options.get("style"),
            layer_a_after=bool(options.get("also_layer_a_text")),
        )
    except (RuntimeError, TimeoutError, urllib.error.URLError) as e:
        raise ValueError(f"Layer B rewrite failed: {e}") from e
    return out, stats


def _batch_items(
    body: dict[str, Any],
) -> list[tuple[str, bytes, dict[str, Any], str | None]]:
    """Decode a batch request's 'files' array into (name, data, options, error) tuples.

    A malformed individual entry (bad base64, unknown option) becomes an error
    string paired with that entry rather than raising, so one bad file never
    aborts the rest of the batch. Only 'files' itself being missing, empty, or
    over MAX_BATCH_FILES raises — that is a malformed request, not a per-file
    problem.
    """
    files = body.get("files")
    if not isinstance(files, list):
        raise ValueError("missing array field 'files'")
    if not files:
        raise ValueError("'files' must not be empty")
    if len(files) > MAX_BATCH_FILES:
        raise ValueError(f"'files' exceeds the {MAX_BATCH_FILES}-file batch limit")

    items: list[tuple[str, bytes, dict[str, Any], str | None]] = []
    for entry in files:
        if not isinstance(entry, dict):
            items.append(("", b"", {}, "each entry in 'files' must be an object"))
            continue
        try:
            data, name = _decode_input(entry)
        except ValueError as e:
            fallback_name = entry.get("name") if isinstance(entry.get("name"), str) else ""
            items.append((fallback_name, b"", {}, str(e)))
            continue
        try:
            options = _parse_clean_options(entry.get("options"))
        except ValueError as e:
            items.append((name, b"", {}, str(e)))
            continue
        items.append((name, data, options, None))
    return items


def _suspicious_report(report: dict[str, Any]) -> dict[str, Any]:
    """Break the collapsed `suspicious` boolean into explicit evidence classes.

    Each class keeps its own evidentiary weight and a plain-language
    `description`, so a downstream agent can weigh the signals rather than
    treating one boolean as a unified provenance judgment.
    """
    detectors = report.get("text_detectors") or []
    synthid_wm = synthid_is_watermarked(report.get("synthid"))
    detected_wm = (
        any(entry.get("available") and entry.get("is_watermarked") for entry in detectors)
        or synthid_wm
    )
    stylometry = report.get("stylometry") or {}
    styl_score = stylometry.get("score") or 0.0
    styl_present = stylometry.get("status") == "ok" and styl_score >= 0.65

    classes = {
        "provenance": {
            "present": bool(report.get("has_c2pa") or report.get("has_ai_metadata")),
            "strength": "definitive",
            "description": _SUSPICIOUS_CLASS_DESCRIPTIONS["provenance"],
            "signals": {
                "has_c2pa": bool(report.get("has_c2pa")),
                "has_ai_metadata": bool(report.get("has_ai_metadata")),
            },
        },
        "layer_a_unicode": {
            "present": bool(report.get("suspicious_total")),
            "strength": "deterministic",
            "description": _SUSPICIOUS_CLASS_DESCRIPTIONS["layer_a_unicode"],
            "signals": {"suspicious_total": report.get("suspicious_total", 0)},
        },
        "watermark_detector": {
            "present": detected_wm,
            "strength": "scheme_specific",
            "description": _SUSPICIOUS_CLASS_DESCRIPTIONS["watermark_detector"],
            "signals": {
                "detected_any": detected_wm,
                "detectors": detectors,
                "synthid": report.get("synthid"),
            },
        },
        "stylometry": {
            "present": styl_present,
            "strength": "heuristic",
            "description": _SUSPICIOUS_CLASS_DESCRIPTIONS["stylometry"],
            "signals": {
                "score": stylometry.get("score"),
                "density_tier": stylometry.get("density_tier"),
            },
        },
    }

    return {
        "verdict": any(c["present"] for c in classes.values()),
        "description": (
            "Combined across heterogeneous evidence classes. A hint to inspect "
            "further, not a single provenance judgment: a file flagged here is "
            "not necessarily watermark-free or human-authored."
        ),
        "classes": classes,
    }


def _inspect_payload(data: bytes, name: str, run_detect: bool) -> dict[str, Any]:
    """Inspect a file and return findings plus a structured suspicious report."""
    kind = classify_bytes(data, Path(name).suffix)
    if kind == "unknown":
        return {
            "ok": True,
            "kind": "unknown",
            "report": {"note": "unrecognized format; use a filename with a known extension"},
            "suspicious": _suspicious_report({}),
        }
    with tempfile.TemporaryDirectory(prefix="wm-inspect-") as tmp:
        path = _tmp_path(Path(tmp), name or "input")
        path.write_bytes(data)
        if kind == "text":
            if looks_binary(data):
                raise ValueError(
                    "refusing to inspect bytes that look like a binary container as text"
                )
            raw_text = data.decode("utf-8", errors="surrogateescape")
            report = inspect_text(raw_text).to_dict()
            s_rep = score_text_stylometry(raw_text, path=name or "<text>")
            report["stylometry"] = s_rep.to_dict()
            if run_detect:
                report["text_detectors"] = run_all_text_detectors(raw_text)
        elif kind == "image":
            report = inspect_image(path, data=data).to_dict()
        elif kind == "av":
            report = inspect_av(path, data=data).to_dict()
        else:
            report = inspect_container(path, data=data).to_dict()
    synthid = report.get("synthid") or {}
    synthid_failed = isinstance(synthid, dict) and synthid.get("available") is False
    res: dict[str, Any] = {
        "ok": True,
        "kind": kind,
        "report": report,
        "suspicious": _suspicious_report(report),
    }
    if synthid_failed:
        res["synthid_probe_failed"] = True
    return res


def _detect_payload(data: bytes, name: str) -> dict[str, Any]:
    kind = classify_bytes(data, Path(name).suffix)
    with tempfile.TemporaryDirectory(prefix="wm-detect-") as tmp:
        path = _tmp_path(Path(tmp), name or "input")
        path.write_bytes(data)
        if kind == "text":
            if looks_binary(data):
                raise ValueError(
                    "refusing to detect bytes that look like a binary container as text"
                )
            raw_text = data.decode("utf-8", errors="surrogateescape")
            detections: list[dict[str, Any]] = run_all_text_detectors(raw_text)
            s_rep = score_text_stylometry(raw_text, path=name or "<text>")
            detections.append({"detector": "stylometry", "available": True, **s_rep.to_dict()})
            return {"ok": True, "kind": kind, "detections": detections}
        elif kind == "image":
            score = run_synthid_score(path, data=data)
            if score is None:
                score = {
                    "detector": "synthid",
                    "available": False,
                    "error": (
                        "no SynthID scorer configured (set "
                        "WATERMARKS_SYNTHID_SCORER_URL or REVERSE_SYNTHID_DIR)"
                    ),
                }
            else:
                score.setdefault("detector", "synthid")
            detections = [score]
            return {"ok": True, "kind": kind, "detections": detections}
        elif kind == "av":
            return {
                "ok": True,
                "kind": kind,
                "detections": [],
                "report": inspect_av(path, data=data).to_dict(),
            }
        else:
            detections = []
            report = inspect_container(path, data=data).to_dict()
            return {
                "ok": True,
                "kind": kind,
                "detections": detections,
                "report": report,
            }


def _clean_payload(data: bytes, name: str, options: dict[str, Any]) -> dict[str, Any]:
    kind = classify_bytes(data, Path(name).suffix)
    if kind == "unknown":
        raise ValueError(
            "unrecognized file format; use a filename with a known extension "
            "(e.g. notes.txt) or a supported image/container name"
        )

    with tempfile.TemporaryDirectory(prefix="wm-clean-") as tmp:
        tmpdir = Path(tmp)
        src = _tmp_path(tmpdir, name or "input")
        src.write_bytes(data)
        if kind == "text":
            if looks_binary(data):
                raise ValueError(
                    "refusing to clean bytes that look like a binary container as text"
                )
            text = data.decode("utf-8", errors="surrogateescape")
            detect_before = bool(options.get("detect_before"))
            detect_after = bool(options.get("detect_after"))
            detector_reports: dict[str, Any] = {}
            if detect_before:
                detector_reports["before"] = run_text_detectors(text)
            cleaned, stats = clean_text(
                text,
                nfkc=bool(options.get("nfkc")),
                aggressive_homoglyphs=bool(options.get("aggressive_homoglyphs")),
                normalize_spaces=bool(options.get("normalize_spaces", True)),
            )
            # A07: Normal text clean is Layer A only by default (zero paraphrase, zero network).
            # Layer B is an explicit opt-in only via options.strategy or options.layer_b.
            strategy = options.get("strategy")
            if not strategy and (options.get("layer_b") or options.get("require_layer_b")):
                strategy = _DEFAULT_STRATEGY
                if not strategy:
                    raise ValueError(
                        "Layer B rewrite is required for text cleaning; configure a "
                        "default strategy (config/clean_strategy.json) or pass "
                        "options.strategy"
                    )
            elif _DEFAULT_STRATEGY is None and not options:
                raise ValueError(
                    "Layer B rewrite is required for text cleaning; configure a "
                    "default strategy (config/clean_strategy.json) or pass "
                    "options.strategy"
                )

            layer_b = None
            if strategy:
                cleaned, layer_b = _apply_layer_b(cleaned, strategy, options)
            if detect_after:
                detector_reports["after"] = run_text_detectors(cleaned)
            cleaned_bytes = cleaned.encode("utf-8", errors="surrogateescape")
            report: dict[str, Any] = {"kind": "text", "stats": stats, "length": len(cleaned)}
            if layer_b is not None:
                report["layer_b"] = layer_b
            if detector_reports:
                report["text_detectors"] = detector_reports
        elif kind == "image":
            ext = Path(name).suffix
            if not ext:
                from image_meta import detect_format

                fmt_name = detect_format(data)
                ext = f".{fmt_name}" if fmt_name != "unknown" else ".png"
            dest = _tmp_path(tmpdir, f"out{ext}")
            strip_all = not bool(options.get("keep_non_ai_metadata"))
            if "strip_all_metadata" in options:
                strip_all = bool(options["strip_all_metadata"])
            remove_pixel = options.get("remove_pixel")
            if remove_pixel not in (None, "ctrlregen", "diffusion"):
                raise ValueError("remove_pixel must be one of: ctrlregen, diffusion")
            result = clean_image(
                src,
                dest,
                strip_all_metadata=strip_all,
                remove_pixel=remove_pixel,
            )
            if bool(options.get("detect_before")) and result.get("synthid_before") is None:
                result["synthid_before"] = run_synthid_score(src)
            if bool(options.get("detect_after")) and result.get("synthid_after") is None:
                result["synthid_after"] = run_synthid_score(dest)
            cleaned_bytes = dest.read_bytes()
            report = {"kind": "image", **result}
        elif kind == "av":
            dest = _tmp_path(tmpdir, f"out{Path(name).suffix or '.bin'}")
            strip_all = not bool(options.get("keep_non_ai_metadata"))
            if "strip_all_metadata" in options:
                strip_all = bool(options["strip_all_metadata"])
            remove_pixel = options.get("remove_pixel")
            if remove_pixel not in (None, "ctrlregen", "diffusion"):
                raise ValueError("remove_pixel must be one of: ctrlregen, diffusion")
            result = clean_av(src, dest, strip_all_metadata=strip_all)
            # Only run the audio chain on audio-only media. WAV/MP3/FLAC are
            # definitive audio containers (no video stream possible); the
            # MP4-family/OGG audio names (.m4a/.aac/.ogg/.opus) could be a
            # mislabeled video, so only treat those as audio when a stream probe
            # confirms there is no video track (an inconclusive probe is not
            # "no video", to avoid dropping a video track via the -vn re-encode).
            definitely_audio = is_audio_format(result.get("format", ""))
            is_audio = definitely_audio or (is_audio_name(name) and media_has_video(src) is False)
            if is_audio and options.get("remove_audio_watermark"):
                # The container-clean dest above is "out" + the input suffix, so an
                # .m4a input made both paths "out.m4a". ffmpeg refuses to edit a file
                # in place, which silently skipped the chain while /clean still 200'd,
                # so keep the re-encode dest literally distinct (an input suffix can
                # never be "-audio.m4a").
                audio_dest = _tmp_path(tmpdir, "out-audio.m4a")
                audio_res = audio_purify(dest, audio_dest)
                result["audio_mark_removal"] = audio_res
                if audio_res.get("available"):
                    dest = audio_dest
                    result["actions"].append(
                        f"destructive audio watermark chain (tempo {audio_res.get('tempo')}x, "
                        f"{audio_res.get('pitch_semitones'):+.1f} semitones, "
                        f"{audio_res.get('codec')})"
                    )
                    # The chain re-encodes to M4A, so the metadata-clean report
                    # fields are stale; recompute them from the final file and
                    # reflect the new container, not the source format.
                    after = inspect_av(dest)
                    result["format"] = after.format
                    result["bytes_out"] = dest.stat().st_size
                    result["changed"] = True
                    result["still_has_c2pa"] = after.has_c2pa
                    result["still_has_ai_metadata"] = after.has_ai_metadata
                    result["post_findings"] = after.findings
                else:
                    result["actions"].append(
                        "destructive audio watermark chain skipped: "
                        f"{audio_res.get('error', 'unknown error')}"
                    )
            elif remove_pixel:
                pix = video_purify(dest, dest, remove_pixel=remove_pixel)
                result["pixel_removal"] = pix
                engine = "CtrlRegen" if remove_pixel == "ctrlregen" else "DiffusionPurification"
                if pix.get("available"):
                    result["actions"].append(
                        f"{engine} per-frame video purification "
                        f"({pix.get('frames_purified')}/{pix.get('frames_total')} frames)"
                    )
                    # The remux re-encodes the video, so the metadata-clean
                    # report fields are stale; recompute them from the final file.
                    after = inspect_av(dest)
                    result["bytes_out"] = dest.stat().st_size
                    result["changed"] = True
                    result["still_has_c2pa"] = after.has_c2pa
                    result["still_has_ai_metadata"] = after.has_ai_metadata
                    result["post_findings"] = after.findings
                else:
                    result["actions"].append(
                        f"per-frame video purification skipped: {pix.get('error', 'unknown error')}"
                    )
            cleaned_bytes = dest.read_bytes()
            report = {"kind": "av", **result}
        else:
            ext = Path(name).suffix
            container_fmt = None
            if not ext:
                from container_meta import detect_container_format

                container_fmt = detect_container_format(Path("input"), data)
                ext_map = {
                    "svg": ".svg",
                    "pdf": ".pdf",
                    "docx": ".docx",
                    "xlsx": ".xlsx",
                    "pptx": ".pptx",
                    "odt": ".odt",
                    "epub": ".epub",
                    "html": ".html",
                    "markdown": ".md",
                }
                ext = ext_map.get(container_fmt, "")
            effective_fmt = container_fmt or (ext.lstrip(".").lower() if ext else "unknown")
            norm_spaces_default = False if effective_fmt in ("docx", "xlsx", "pptx") else True
            norm_spaces = bool(options.get("normalize_spaces", norm_spaces_default))
            if effective_fmt in ("docx", "xlsx", "pptx"):
                norm_spaces = False  # Strictly forbidden for DOCX/XLSX/PPTX to protect typography & NBSP

            dest = _tmp_path(tmpdir, f"out{ext}")
            result = clean_container(
                src,
                dest,
                fmt=container_fmt,
                also_layer_a_text=bool(options.get("also_layer_a_text", True)),
                deep_images=str(options.get("deep_images", "auto")),
                clean_attachments=str(options.get("clean_attachments", DEFAULT_CLEAN_ATTACHMENTS)),
                normalize_spaces=norm_spaces,
            )
            cleaned_bytes = dest.read_bytes()
            report = {"kind": "container", **result}
        report.pop("input", None)
        report.pop("output", None)

    return {
        "ok": True,
        "kind": kind,
        "cleaned": base64.b64encode(cleaned_bytes).decode("ascii"),
        "report": report,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = f"watermarks-remover/{VERSION}"

    def log_message(self, fmt: str, *args: object) -> None:
        # Local time with UTC offset, e.g. "2026-08-27 14:03:11 +0300" — readable
        # without conversion, and unambiguous across timezones/DST.
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        eprint(f"[{stamp}] {self.address_string()} - {fmt % args}")

    def _authorized(self) -> bool:
        if not API_KEY:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {API_KEY}"

    def _read_json(self) -> dict[str, Any] | None:
        raw = self.headers.get("Content-Length")
        if raw is None or not raw.isdigit():
            return None
        length = int(raw)
        if length > MAX_BODY_BYTES:
            return None
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(body, dict):
            return None
        return body

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        data = _json_ok(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, file_path: Path, content_type: str) -> None:
        try:
            data = file_path.read_bytes()
        except OSError:
            self._respond(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if not self._authorized():
            self._respond(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if path == "/health":
            self._respond(HTTPStatus.OK, {"ok": True, "version": VERSION})
        elif path == "/capabilities":
            self._respond(HTTPStatus.OK, {"ok": True, **capabilities()})
        elif path == "/openapi.json":
            self._respond(HTTPStatus.OK, openapi_spec())
        else:
            web_dir = Path(__file__).resolve().parent.parent / "web"
            if not web_dir.is_dir():
                if hasattr(sys, "_MEIPASS"):
                    base = Path(getattr(sys, "_MEIPASS"))
                    if (base / "service" / "web").is_dir():
                        web_dir = base / "service" / "web"
                    elif (base / "web").is_dir():
                        web_dir = base / "web"
                elif hasattr(sys, "executable"):
                    exe_dir = Path(sys.executable).resolve().parent
                    if (exe_dir / "service" / "web").is_dir():
                        web_dir = exe_dir / "service" / "web"
                    elif (exe_dir / "_internal" / "service" / "web").is_dir():
                        web_dir = exe_dir / "_internal" / "service" / "web"

            if path in ("/", "/index.html"):
                target = web_dir / "index.html"
                if target.is_file():
                    self._serve_file(target, "text/html; charset=utf-8")
                    return
            elif path == "/app.js":
                target = web_dir / "app.js"
                if target.is_file():
                    self._serve_file(target, "application/javascript; charset=utf-8")
                    return
            elif path == "/app.css":
                target = web_dir / "app.css"
                if target.is_file():
                    self._serve_file(target, "text/css; charset=utf-8")
                    return
            self._respond(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not self._authorized():
            self._respond(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if path not in (
            "/inspect",
            "/clean",
            "/verify",
            "/detect",
            "/watermark",
            "/batch",
            "/inspect/batch",
            "/detect/batch",
            "/clean/batch",
            "/watermark/batch",
        ):
            self._respond(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        body = self._read_json()
        if body is None:
            raw_len = self.headers.get("Content-Length")
            oversized = raw_len is not None and raw_len.isdigit() and int(raw_len) > MAX_BODY_BYTES
            self._respond(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE if oversized else HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid request body"},
            )
            return
        try:
            if path == "/batch":
                self._handle_batch(body)
            elif path == "/inspect/batch":
                self._handle_inspect_batch(body)
            elif path == "/detect/batch":
                self._handle_detect_batch(body)
            elif path == "/clean/batch":
                self._handle_clean_batch(body)
            elif path == "/watermark/batch":
                self._handle_watermark_batch(body)
            elif path == "/watermark":
                self._handle_watermark(body)
            elif path == "/verify":
                self._handle_verify(body)
            else:
                data, name = _decode_input(body)
                if path == "/inspect":
                    self._handle_inspect(data, name, body)
                elif path == "/detect":
                    self._handle_detect(data, name)
                else:
                    self._handle_clean(data, name, body)
        except ValueError as e:
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(e)})
        except Exception as e:
            self.log_error("error handling %s: %r", path, e)
            self._respond(
                HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "internal error"}
            )

    def _handle_verify(self, body: dict[str, Any]) -> None:
        if not isinstance(body, dict):
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "request body must be a JSON object"})
            return
        if "original" not in body or "candidate" not in body:
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing 'original' or 'candidate' field"})
            return
        try:
            orig_bytes = base64.b64decode(body["original"], validate=True)
            cand_bytes = base64.b64decode(body["candidate"], validate=True)
        except Exception:
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid base64 in 'original' or 'candidate'"})
            return

        name = body.get("name", "")
        cand_name = body.get("candidate_name", name)
        req_fmt = body.get("format", "").lower().lstrip(".")
        from container_meta import detect_container_format
        orig_fmt = Path(name).suffix.lower().lstrip(".") if name else req_fmt
        cand_fmt = Path(cand_name).suffix.lower().lstrip(".") if cand_name else req_fmt

        orig_sha = hashlib.sha256(orig_bytes).hexdigest()
        cand_sha = hashlib.sha256(cand_bytes).hexdigest()

        # Phase 9: Preflight both original and candidate before invoking format fidelity validators
        from security import require_safe_zip_container, SecurityViolation
        for label, b in (("original", orig_bytes), ("candidate", cand_bytes)):
            if b.startswith(b"PK") or orig_fmt in ("docx", "xlsx", "pptx") or cand_fmt in ("docx", "xlsx", "pptx"):
                try:
                    require_safe_zip_container(b)
                except SecurityViolation as sv:
                    st = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if sv.is_limit else HTTPStatus.BAD_REQUEST
                    self._respond(st, {
                        "ok": False,
                        "status": "ERROR",
                        "format": orig_fmt or cand_fmt or "unknown",
                        "error_code": "PROCESSING_LIMIT_EXCEEDED" if sv.is_limit else "INVALID_CONTAINER",
                        "error_message": f"Verification {label} file failed security preflight: {sv.finding.reason}",
                        "rule_id": sv.finding.rule_id,
                        "validation": {"structural_invariants_passed": False},
                        "invariants": [],
                        "warnings": [sv.finding.reason],
                        "hashes": {"original": orig_sha, "candidate": cand_sha},
                    })
                    return

        if not orig_fmt or orig_fmt == "bin":
            orig_fmt = detect_container_format(Path(name or "dummy.bin"), orig_bytes)
        if not cand_fmt or cand_fmt == "bin":
            cand_fmt = detect_container_format(Path(cand_name or "dummy.bin"), cand_bytes)

        if orig_fmt != cand_fmt:
            self._respond(HTTPStatus.BAD_REQUEST, {
                "ok": False,
                "status": "FAIL",
                "format": orig_fmt or "unknown",
                "error_code": "MISMATCHED_FORMATS",
                "error": f"Mismatched verification pair formats: original is '{orig_fmt}', candidate is '{cand_fmt}'",
                "validation": {"structural_invariants_passed": False},
                "invariants": [],
                "warnings": [f"Mismatched verification pair formats: original is '{orig_fmt}', candidate is '{cand_fmt}'"],
                "hashes": {"original": orig_sha, "candidate": cand_sha},
            })
            return

        fmt = orig_fmt

        if fmt not in ("docx", "xlsx", "pptx"):
            self._respond(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {
                "ok": False,
                "status": "UNSUPPORTED",
                "format": fmt,
                "error_code": "UNSUPPORTED_VERIFICATION_CAPABILITY",
                "error": f"Verification capability is currently supported only for docx, xlsx, and pptx documents (got: '{fmt}'). Dedicated verifiers for other formats are planned for subsequent phases.",
                "validation": {
                    "structural_invariants_passed": False,
                },
                "invariants": [],
                "warnings": [f"Verification not supported for format: {fmt}"],
                "hashes": {
                    "original": orig_sha,
                    "candidate": cand_sha,
                },
            })
            return

        if fmt == "docx":
            from tools.verify_document_fidelity import analyze_docx_fidelity
            try:
                fidelity = analyze_docx_fidelity(orig_bytes, cand_bytes, perform_visual=False)
                is_pass = (fidelity.get("overall") == "PASS")
                invariants = [
                    f"paragraphs: {fidelity['paragraphs'][0]} -> {fidelity['paragraphs'][1]}",
                    f"runs: {fidelity['runs'][0]} -> {fidelity['runs'][1]}",
                    f"tables: {fidelity['tables'][0]} -> {fidelity['tables'][1]}",
                    f"manual_page_breaks: {fidelity['manual_page_breaks'][0]} -> {fidelity['manual_page_breaks'][1]}",
                    f"visible_text_exact: {fidelity['visible_text_exact']}",
                    f"non_target_parts_identical: {fidelity['non_target_parts_identical']}",
                ]
                warnings = []
            except Exception as e:
                is_pass = False
                invariants = []
                warnings = [f"Fidelity verification error: {e}"]
        elif fmt == "xlsx":
            from xlsx import XlsxPackage, XlsxFidelityValidator
            try:
                b_pkg = XlsxPackage(orig_bytes)
                a_pkg = XlsxPackage(cand_bytes)
                changed = {m for m in b_pkg.member_order if b_pkg.get_hash(m) != a_pkg.get_hash(m)}
                dropped = set(b_pkg.member_order) - set(a_pkg.member_order)
                validator = XlsxFidelityValidator(b_pkg, a_pkg, changed, dropped)
                fidelity_report = validator.validate()
                is_pass = fidelity_report.passed
                invariants = list(fidelity_report.invariants)
                warnings = list(fidelity_report.warnings)
                if not is_pass:
                    warnings.extend(fidelity_report.errors)
            except Exception as e:
                is_pass = False
                invariants = []
                warnings = [f"XLSX fidelity verification error: {e}"]
        else:  # pptx
            from pptx import PptxPackage, PptxFidelityValidator
            try:
                b_pkg = PptxPackage(orig_bytes)
                a_pkg = PptxPackage(cand_bytes)
                changed = {m for m in b_pkg.member_order if b_pkg.get_hash(m) != a_pkg.get_hash(m)}
                dropped = set(b_pkg.member_order) - set(a_pkg.member_order)
                validator = PptxFidelityValidator(b_pkg, a_pkg, changed, dropped)
                fidelity_report = validator.validate()
                is_pass = fidelity_report.passed
                invariants = list(fidelity_report.invariants)
                warnings = list(fidelity_report.warnings)
                if not is_pass:
                    warnings.extend(fidelity_report.errors)
            except Exception as e:
                is_pass = False
                invariants = []
                warnings = [f"PPTX fidelity verification error: {e}"]

        res_status = "PASS" if is_pass else "FAIL"
        resp_code = HTTPStatus.OK if is_pass else HTTPStatus.UNPROCESSABLE_ENTITY
        self._respond(resp_code, {
            "ok": is_pass,
            "status": res_status,
            "format": fmt,
            "validation": {
                "structural_invariants_passed": is_pass,
            },
            "invariants": invariants,
            "warnings": warnings,
            "hashes": {
                "original": orig_sha,
                "candidate": cand_sha,
            },
        })

    def _handle_inspect(self, data: bytes, name: str, body: dict[str, Any]) -> None:
        run_detect = body.get("detect") is True
        if run_detect:
            self._respond(HTTPStatus.OK, _inspect_payload(data, name, run_detect))
            return

        kind = classify_bytes(data, Path(name).suffix)
        ext = Path(name).suffix.lower().lstrip(".")
        if not ext and kind == "unknown":
            self._respond(HTTPStatus.OK, {
                "ok": True,
                "kind": "unknown",
                "report": {"note": "unrecognized format; use a filename with a known extension"},
                "suspicious": _suspicious_report({}),
            })
            return

        mode_str = body.get("mode", "safe")
        if not isinstance(mode_str, str) or mode_str.lower() not in ("safe", "balanced", "aggressive"):
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Invalid mode: {mode_str}"})
            return

        mode = ProcessingMode(mode_str.upper())
        pipeline = Pipeline()
        report = pipeline.inspect(data, filename=name, mode=mode)

        if report.status == PipelineStatus.ERROR:
            status_code = error_code_to_http_status(report.error_code)
            self._respond(status_code, {"ok": False, "error": report.error_message, "report": report.to_dict()})
            return
        if report.status == PipelineStatus.UNSUPPORTED:
            self._respond(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "Unsupported file format", "report": report.to_dict()})
            return

        report_dict = report.to_dict()
        report_dict["suspicious_total"] = len(report.inspection.findings)
        report_dict["has_c2pa"] = any(f.category == "c2pa" for f in report.inspection.findings)
        report_dict["has_ai_metadata"] = any(f.category == "ai_metadata" for f in report.inspection.findings)
        suspicious_obj = _suspicious_report(report_dict)

        self._respond(HTTPStatus.OK, {
            "ok": True,
            "kind": kind,
            "suspicious": suspicious_obj,
            "report": report_dict,
        })

    def _handle_inspect_batch(self, body: dict[str, Any]) -> None:
        items = _batch_items(body)
        run_detect = body.get("detect") is True
        results = []
        for name, data, _options, error in items:
            if error is not None:
                results.append({"name": name, "ok": False, "error": error})
                continue
            try:
                payload = _inspect_payload(data, name, run_detect)
            except ValueError as e:
                results.append({"name": name, "ok": False, "error": str(e)})
                continue
            results.append({"name": name, **payload})
        self._respond(HTTPStatus.OK, {"ok": True, "results": results})

    def _handle_detect(self, data: bytes, name: str) -> None:
        self._respond(HTTPStatus.OK, _detect_payload(data, name))

    def _handle_detect_batch(self, body: dict[str, Any]) -> None:
        items = _batch_items(body)
        results = []
        for name, data, _options, error in items:
            if error is not None:
                results.append({"name": name, "ok": False, "error": error})
                continue
            try:
                payload = _detect_payload(data, name)
            except ValueError as e:
                results.append({"name": name, "ok": False, "error": str(e)})
                continue
            results.append({"name": name, **payload})
        self._respond(HTTPStatus.OK, {"ok": True, "results": results})

    def _handle_clean(self, data: bytes, name: str, body: dict[str, Any]) -> None:
        opts_raw = _parse_clean_options(body.get("options"))
        mode_str = body.get("mode") or opts_raw.get("mode") or "safe"
        if not isinstance(mode_str, str) or mode_str.lower() not in ("safe", "balanced", "aggressive"):
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Invalid mode: {mode_str}"})
            return

        remove_pixel = opts_raw.get("remove_pixel")
        if remove_pixel not in (None, "ctrlregen", "diffusion"):
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "remove_pixel must be one of: ctrlregen, diffusion"})
            return

        kind = classify_bytes(data, Path(name).suffix)
        ext = Path(name).suffix.lower().lstrip(".")
        if not ext and kind == "unknown":
            self._respond(HTTPStatus.BAD_REQUEST, {
                "ok": False,
                "error": "unrecognized file format; use a filename with a known extension (e.g. notes.txt) or a supported image/container name"
            })
            return

        dry_run = bool(body.get("dry_run") or opts_raw.get("dry_run", False))
        mode = ProcessingMode(mode_str.upper())
        pipeline = Pipeline()

        if dry_run:
            cleaned_bytes, report = pipeline.clean(data, filename=name, mode=mode, dry_run=True, options=opts_raw)
            if report.status == PipelineStatus.ERROR:
                status_code = error_code_to_http_status(report.error_code)
                self._respond(status_code, {"ok": False, "error": report.error_message, "report": report.to_dict()})
                return
            if report.status == PipelineStatus.UNSUPPORTED:
                self._respond(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "Unsupported file format", "report": report.to_dict()})
                return
            report_dict = report.to_dict()
            self._respond(HTTPStatus.OK, {
                "ok": True,
                "kind": kind,
                "cleaned": "",
                "report": report_dict,
            })
            return

        # Real clean
        legacy_res = None
        try:
            legacy_res = _clean_payload(data, name, opts_raw)
        except Exception as e:
            if not isinstance(e, ValueError):
                pass

        cleaned_bytes, report = pipeline.clean(data, filename=name, mode=mode, dry_run=False, options=opts_raw)

        if report.status == PipelineStatus.ERROR:
            status_code = error_code_to_http_status(report.error_code)
            self._respond(status_code, {"ok": False, "error": report.error_message, "report": report.to_dict()})
            return
        if report.status == PipelineStatus.UNSUPPORTED:
            self._respond(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"ok": False, "error": "Unsupported file format", "report": report.to_dict()})
            return
        if report.status == PipelineStatus.VALIDATION_FAILED:
            self._respond(HTTPStatus.UNPROCESSABLE_ENTITY, {"ok": False, "error": "Validation failed", "report": report.to_dict()})
            return

        # Canonical agreement: returned bytes must strictly equal report.output.sha256 (A06)
        if legacy_res and report.input.format != "docx":
            cleaned_b64 = legacy_res.get("cleaned", "")
            try:
                cleaned_bytes = base64.b64decode(cleaned_b64)
                report.output.sha256 = hashlib.sha256(cleaned_bytes).hexdigest()
                report.output.size = len(cleaned_bytes)
                report.output.changed = (cleaned_bytes != data)
            except Exception:
                pass
        else:
            cleaned_b64 = base64.b64encode(cleaned_bytes).decode("ascii")

        report_dict = report.to_dict()
        if legacy_res and "report" in legacy_res:
            for k, v in legacy_res["report"].items():
                if k not in report_dict or k in (
                    "stats",
                    "actions",
                    "format",
                    "audio_mark_removal",
                    "text_detectors",
                    "synthid_before",
                    "synthid_after",
                ):
                    report_dict[k] = v

        report_dict["changed"] = report.output.changed
        report_dict["output"]["sha256"] = report.output.sha256
        report_dict["output"]["size"] = report.output.size
        report_dict["output"]["changed"] = report.output.changed

        if kind == "container":
            try:
                from container_meta import inspect_container
                with tempfile.TemporaryDirectory() as _tmpdir:
                    _ext = f".{report.input.format}" if report.input.format else ".bin"
                    _tmp_f = Path(_tmpdir) / f"cleaned{_ext}"
                    _tmp_f.write_bytes(cleaned_bytes)
                    _after = inspect_container(_tmp_f, fmt=report.input.format if report.input.format == "svg" else None)
                    report_dict["still_has_c2pa"] = getattr(_after, "has_c2pa", False)
            except Exception:
                report_dict["still_has_c2pa"] = False

        self._respond(HTTPStatus.OK, {
            "ok": True,
            "kind": kind,
            "cleaned": cleaned_b64,
            "report": report_dict,
        })

    def _handle_clean_batch(self, body: dict[str, Any]) -> None:
        """Compatibility batch clean endpoint routing through canonical Pipeline (A08)."""
        items = _batch_items(body)
        results = []
        for name, data, options, error in items:
            if error is not None:
                results.append({"name": name, "ok": False, "error": error})
                continue
            try:
                payload = _clean_payload(data, name, options)
                cleaned_b64 = payload.get("cleaned", "")
                cleaned_bytes = base64.b64decode(cleaned_b64)
                rep_dict = payload.get("report", {})
                rep_dict["changed"] = (cleaned_bytes != data)
                rep_dict["output"] = {
                    "sha256": hashlib.sha256(cleaned_bytes).hexdigest(),
                    "size": len(cleaned_bytes),
                    "changed": (cleaned_bytes != data),
                }
                results.append({
                    "name": name,
                    "ok": True,
                    "cleaned": cleaned_b64,
                    "report": rep_dict,
                })
            except ValueError as e:
                results.append({"name": name, "ok": False, "error": str(e)})
            except Exception as e:
                results.append({"name": name, "ok": False, "error": str(e)})
        self._respond(HTTPStatus.OK, {"ok": True, "results": results})

    def _handle_batch(self, body: dict[str, Any]) -> None:
        if not isinstance(body, dict):
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "request body must be a JSON object"})
            return
        files = body.get("files")
        if not isinstance(files, list) or len(files) == 0:
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "'files' array is required and must not be empty"})
            return

        from batch_processor import (
            MAX_BATCH_FILES,
            MAX_BATCH_INLINE_OUTPUT_BYTES,
            MAX_BATCH_TOTAL_BYTES,
            BatchLimitExceededError,
            BatchProcessor,
        )

        if len(files) > MAX_BATCH_FILES:
            self._respond(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": f"Batch file count ({len(files)}) exceeds maximum allowed ({MAX_BATCH_FILES})"})
            return

        mode_str = body.get("mode", "safe")
        if not isinstance(mode_str, str) or mode_str.lower() not in ("safe", "balanced", "aggressive"):
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Invalid mode: {mode_str}"})
            return

        mode = ProcessingMode(mode_str.upper())
        dry_run = bool(body.get("dry_run", False))
        operation = body.get("operation", "clean")
        if operation not in ("clean", "inspect"):
            self._respond(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"Invalid operation: {operation}"})
            return

        processor = BatchProcessor()
        try:
            batch_report = processor.process_items(files, mode=mode, dry_run=dry_run, operation=operation)
        except BatchLimitExceededError as e:
            self._respond(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": str(e)})
            return
        except Exception as e:
            self._respond(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": f"Batch processing failed: {e}"})
            return

        # Explicit transport envelope separating canonical metadata report from file payload transport
        outputs_limit_bytes = int(os.environ.get("WATERMARKS_MAX_BATCH_INLINE_OUTPUT_BYTES", str(MAX_BATCH_INLINE_OUTPUT_BYTES)))
        outputs: list[dict[str, Any]] = []
        outputs_included = False
        output_delivery = "none"

        if dry_run or operation == "inspect":
            output_delivery = "dry_run" if dry_run else "inspect"
            outputs_included = False
        else:
            # Calculate raw cleaned output size before any expensive base64 encoding
            cleaned_items = [
                item for item in batch_report.items
                if item.status == "CLEANED" and item.cleaned_bytes is not None
            ]
            total_raw_output_bytes = sum(len(item.cleaned_bytes) for item in cleaned_items)

            if total_raw_output_bytes > outputs_limit_bytes:
                # Do NOT encode base64 or build oversized payload
                outputs_included = False
                output_delivery = "not_available_inline"
            else:
                for item in cleaned_items:
                    sha256 = (
                        item.report["output"]["sha256"]
                        if item.report and "output" in item.report and "sha256" in item.report["output"]
                        else hashlib.sha256(item.cleaned_bytes).hexdigest()
                    )
                    outputs.append({
                        "index": item.index,
                        "name": item.input_path,
                        "sha256": sha256,
                        "content_base64": base64.b64encode(item.cleaned_bytes).decode("ascii"),
                    })
                outputs_included = True
                output_delivery = "inline"

        resp_envelope: dict[str, Any] = {
            "ok": True,
            "report": batch_report.to_dict(),
            "outputs_included": outputs_included,
            "output_delivery": output_delivery,
            "outputs": outputs,
        }
        if output_delivery == "not_available_inline":
            resp_envelope["outputs_limit_bytes"] = outputs_limit_bytes
            resp_envelope["outputs_omitted_reason"] = (
                f"Total cleaned output ({total_raw_output_bytes} bytes) exceeds inline response limit ({outputs_limit_bytes} bytes)"
            )

        self._respond(HTTPStatus.OK, resp_envelope)

    def _extract_text_input(self, body: dict[str, Any]) -> tuple[str, str]:
        """Extract raw text and optional name from a watermark request body."""
        name = body.get("name") if isinstance(body.get("name"), str) else ""
        if "text" in body:
            raw_text = body["text"]
            if not isinstance(raw_text, str) or not raw_text.strip():
                raise ValueError("'text' must be a non-empty string")
            return raw_text, name
        if "file" in body:
            data, decoded_name = _decode_input(body)
            if looks_binary(data):
                raise ValueError("refusing to treat binary content as text for watermarking")
            return data.decode("utf-8", errors="surrogateescape"), name or decoded_name
        raise ValueError("request must include 'text' or base64 'file'")

    def _handle_watermark(self, body: dict[str, Any]) -> None:
        text, _name = self._extract_text_input(body)
        keys = body.get("keys")
        options = parse_watermark_options(body.get("options"))
        timeout = resolve_timeout(None)
        res = generate_watermark_text(text, keys=keys, options=options, timeout=timeout)
        if res.get("ok"):
            self._respond(HTTPStatus.OK, res)
        else:
            self._respond(_watermark_error_status(res), res)

    def _handle_watermark_batch(self, body: dict[str, Any]) -> None:
        files = body.get("files")
        if not isinstance(files, list):
            raise ValueError("missing array field 'files'")
        if not files:
            raise ValueError("'files' must not be empty")
        if len(files) > MAX_BATCH_FILES:
            raise ValueError(f"'files' exceeds the {MAX_BATCH_FILES}-file batch limit")

        backend_configured = bool(
            os.environ.get("WATERMARKS_SYNTHID_TEXT_URL", "").strip()
            or os.environ.get("MARKLLM_DIR", "").strip()
        )
        if not backend_configured:
            self._respond(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "ok": False,
                    "error": (
                        "no text watermark generator configured (set WATERMARKS_SYNTHID_TEXT_URL "
                        "for the sidecar or MARKLLM_DIR for local execution)"
                    ),
                },
            )
            return

        batch_budget = resolve_timeout(None)
        deadline = time.monotonic() + batch_budget

        results = []
        timed_out = False
        for entry in files:
            if not isinstance(entry, dict):
                results.append(
                    {"name": "", "ok": False, "error": "each entry in 'files' must be an object"}
                )
                continue
            name = entry.get("name") if isinstance(entry.get("name"), str) else ""

            remaining = deadline - time.monotonic()
            if remaining <= 0 or timed_out:
                timed_out = True
                results.append({"name": name, "ok": False, "error": "batch deadline exceeded"})
                continue

            try:
                text, extracted_name = self._extract_text_input(entry)
                entry_name = name or extracted_name
                keys = entry.get("keys")
                options = parse_watermark_options(entry.get("options"))
                res = generate_watermark_text(text, keys=keys, options=options, timeout=remaining)
                if res.get("ok"):
                    results.append({"name": entry_name, **res})
                else:
                    err = res.get("error", "watermark generation failed")
                    if res.get("error_code") == "timeout":
                        timed_out = True
                    results.append({"name": entry_name, "ok": False, "error": err})
            except ValueError as e:
                results.append({"name": name, "ok": False, "error": str(e)})
            except Exception as e:
                self.log_error("watermark batch entry error for %r: %r", name, e)
                results.append({"name": name, "ok": False, "error": "internal error"})

        self._respond(HTTPStatus.OK, {"ok": True, "results": results})


def create_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    api_key: str | None = None,
    strategy_config: Path | str | None = None,
) -> ThreadingHTTPServer:
    """Create and return a configured ThreadingHTTPServer instance without blocking."""
    global API_KEY, _DEFAULT_STRATEGY  # noqa: PLW0603
    if api_key is not None:
        API_KEY = api_key
    if strategy_config:
        _DEFAULT_STRATEGY = _load_default_strategy(Path(strategy_config))
    elif _DEFAULT_STRATEGY is None:
        _DEFAULT_STRATEGY = _load_default_strategy(
            Path(os.environ.get("WATERMARKS_CLEAN_STRATEGY_FILE", "config/clean_strategy.json"))
        )

    if host not in ("127.0.0.1", "localhost", "::1"):
        eprint(f"warning: binding {host} — intended for a trusted network only")
    if API_KEY:
        eprint("API key required for requests")
    else:
        eprint("warning: no API key set — only bind to loopback or a trusted network")

    return ThreadingHTTPServer((host, port), Handler)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default=os.environ.get("WATERMARKS_SERVER_HOST", "127.0.0.1"))
    p.add_argument(
        "--port", type=int, default=int(os.environ.get("WATERMARKS_SERVER_PORT", "8765"))
    )
    p.add_argument("--api-key", default=API_KEY, help="require this bearer token (default: none)")
    p.add_argument(
        "--strategy-config",
        default=os.environ.get("WATERMARKS_CLEAN_STRATEGY_FILE", "config/clean_strategy.json"),
        help="Path to the Layer B strategy config JSON (default: "
        "config/clean_strategy.json; WATERMARKS_CLEAN_STRATEGY_FILE). A strategy "
        "step is 'tactic@intensity' (e.g. 'paraphrase@0.8,mlm@0.2').",
    )
    p.add_argument("-V", "--version", action="store_true", help="print version and exit")
    args = p.parse_args()

    if args.version:
        print(VERSION)
        return 0

    server = create_server(
        host=args.host,
        port=args.port,
        api_key=args.api_key,
        strategy_config=args.strategy_config,
    )
    eprint(f"watermarks-remover service {VERSION} on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        eprint("shutting down")
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
