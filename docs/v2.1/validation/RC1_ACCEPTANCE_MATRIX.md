# ClearMark v2.1.0-RC1 — Acceptance Matrix

| Gate | Focus | Verification Method | Status | Notes |
| :--- | :--- | :--- | :---: | :--- |
| **V0** | **Environment & Freeze** | `git diff v2.0.0 -- service/scripts/docx/` + Fixture Hashes | **PASS** | DOCX core diff EMPTY; Golden (`c05ca5c1be3b020b...`) & Candidate (`7aa5549f6a0e0b78...`) hashes MATCH. |
| **V1** | **Artifact Identity** | `tools/build_review_package.py --audit` | **PASS** | 15/15 audit gates pass, SHA256 `33616f74730a0e026efa751d1fb5d86d5f310e2d66f6de3d34afec3635d716d9` verified. |
| **V2** | **CLI & API Acceptance** | `watermarks` CLI + stdlib HTTP service | **PASS** | `inspect`, `clean` (dry-run & real), `verify` exit 0. HTTP endpoints `/health`, `/capabilities`, `/inspect`, `/clean` return 200. |
| **V3** | **Capability Matrix** | `FormatPolicyRegistry.get_default()` | **PASS** | All 23 canonical format policies registered and mapped. |
| **V4** | **Real-World Corpus** | Real-world synthetic samples | **PASS** | 23/23 policies evaluated (22 bundled + 1 project HEIC fixture). Cleaned, dry-run verified, idempotence verified. |
| **V5** | **Office Lossless Fidelity** | Structural invariant validators | **PASS** | DOCX (runs, paragraphs, tables, layout preserved), XLSX (sheets, cells, formulas preserved), PPTX (slides, geometries preserved), Unicode (diacritics preserved). |
| **V6** | **Negative & Security** | Inert hostile fixtures | **PASS** | 12/12 malformed/hostile fixtures rejected preflight before mutation. Zero unexpected writes or leaks. |
| **V7** | **Batch & Stress** | BatchProcessor + Stress files | **PASS** | Valid 100 batch (100% reconciled, 0 errors), mixed batch (fault isolation verified), stress files (32 MiB limit strictly enforced). |
| **V8** | **UX & Docs Truthfulness** | Capability consistency tests | **PASS** | `test_docs_capabilities_consistency.py` 100% pass; CLI help strings consistent with policies. |
| **V9** | **Soak & Stability** | Multi-cycle processing | **PASS** | 5-cycle loop across multi-format samples: zero memory leak (RSS delta < 0 MiB), output determinism 100%. |
| **V10** | **Final Decision** | Defect triage & promotion gating | **PASS** | 0 S0 (blocker), 0 S1 (major), 0 S2 (moderate), 0 S3 (minor) -> **PROMOTE_TO_V2.1.0**. |

---

## FINAL VALIDATION CLOSURE

| Closure Area | Focus / Scope | Measured Outcome | Status |
| :--- | :--- | :--- | :---: |
| **Soak Closure** | 10 server cycles, 10 clean sessions, 3 batch reruns, 3 UI reloads, 5 idempotence checks | 100% deterministic digests, bounded net RSS growth (+13.8 MiB), zero leaks | **PASS** |
| **CLI Full Contract** | All 5 subcommands (`inspect`, `clean`, `verify`, `capabilities`, `batch`) | Exit codes 0, 2, 3, 4, 5, 6, 7, 10 verified; stdout pure JSON; dry-run zero-write; in-place atomic | **PASS** |
| **HTTP Contract** | Endpoints `/health`, `/capabilities`, `/inspect`, `/clean`, `/verify`, `/batch` | Public mappings 200, 400, 413, 415, 422, 424 verified; zero sensitive document text leakage | **PASS** |
| **Real Browser UI** | Node unit suite + Headless Chrome 153.0.8010.48 CDP automation | Capability init, SAFE default, XSS inert string safety, 3 reload/reconnect cycles pass | **PASS** |
| **Visual Fidelity** | LibreOffice 26.8.0.3 headless rendering (DOCX, XLSX, PPTX) | Page count match (3->3 pages), Calc/Impress open without repair dialogs, layout preserved | **PASS** |
| **Docs Execution** | Representative README commands executed + 16 constants checked | Commands parse, options exist, runtime behavior matches, 16/16 constants match code | **PASS** |
| **Corpus Provenance** | `ClearMark_RC1_Validation_Corpus_v1.zip` SHA256 & manifest | SHA256 `cf5e6dad07452...` verified; 23/23 canonical policies covered (22 bundled + 1 fixture) | **PASS** |
| **Machine-Readable Evidence** | All 9 telemetry JSON files in `artifacts/v2.1/rc1_validation/` | Actual measured values recorded; zero placeholder or synthetic Markdown copies | **COMPLETE** |

