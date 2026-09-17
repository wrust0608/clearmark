# ClearMark Release Policy & Packaging Standards

This document establishes the official release engineering policy, asset conventions, and hygiene rules for ClearMark releases on GitHub.

---

## 1. Versioning Scheme

ClearMark follows Semantic Versioning (`MAJOR.MINOR.PATCH`):

- **Major (`vX.0.0`)**: Incompatible API changes, major architectural overhauls, or breaking format behavior.
- **Minor (`vX.Y.0`)**: Backwards-compatible new user functionality (e.g. desktop host, new media extractors).
- **Patch (`vX.Y.Z`)**: Backwards-compatible bug fixes and security patches.

### Tag Formats

- **Stable Release Tag**: `vX.Y.Z` (e.g., `v2.1.0`, `v2.2.0`)
- **Release Candidate Tag**: `vX.Y.Z-rcN` (e.g., `v2.2.0-rc1`, `v2.2.0-rc2`)

---

## 2. GitHub Release Presentation & Asset Policy

Release pages are intended for **end users**. The public/private GitHub Release presentation must remain clean, accessible, and free of internal engineering clutter.

### Windows Desktop Stable Asset Convention

For stable desktop releases (`vX.Y.Z`), the release assets must contain ONLY:

1. **Windows Installer**:
   `ClearMark-vX.Y.Z-Windows-x64-Setup.exe`
2. **Portable ZIP**:
   `ClearMark-vX.Y.Z-Windows-x64-Portable.zip`
3. **SHA256 Checksums**:
   `ClearMark-vX.Y.Z-SHA256SUMS.txt`

### Windows Desktop Release Candidate (RC) Convention

For release candidates (`vX.Y.Z-rcN`), the release assets must contain ONLY:

1. **Windows Installer**:
   `ClearMark-vX.Y.Z-rcN-Windows-x64-Setup.exe`
2. **Portable ZIP**:
   `ClearMark-vX.Y.Z-rcN-Windows-x64-Portable.zip`
3. **SHA256 Checksums**:
   `ClearMark-vX.Y.Z-rcN-SHA256SUMS.txt`

### Core Engine Baseline Releases

For engine-only or historical core archive releases:
- Archive package: `FINAL_RELEASE_PACKAGE_vX.Y.Z.zip`
- Checksum file: `FINAL_RELEASE_PACKAGE_vX.Y.Z.zip.sha256`

---

## 3. Separation of User Assets vs. Engineering Evidence

### User-Facing Releases (GitHub Releases UI)
- Must contain **only** installable/runnable binaries and cryptographic checksum files.
- Release descriptions must focus on:
  - What the release is
  - Recommended download option
  - How to install, run, and stop the application
  - Summary of what is new
  - Verification checksums

### Engineering Evidence (In-Repo Only)
The following files are **never** attached to public or user-facing GitHub Releases:
- `*_REPORT.md` (e.g., `DESKTOP_ACCEPTANCE_REPORT.md`, `MASTER_REVALIDATION_REPORT.md`)
- `*_MANIFEST.json` (e.g., `DESKTOP_BUILD_MANIFEST.json`, `STABLE_RELEASE_MANIFEST.json`)
- `*_PROVENANCE.json` (e.g., `DESKTOP_BUILD_PROVENANCE.json`, `STABLE_RELEASE_PROVENANCE.json`)
- `PACKAGE_AUDIT.json`
- `PACKAGE_CONTENTS.txt`
- `STABLE_VS_RC1_DIFF.json`
- Test suites, soak test data, or internal validation logs

All engineering evidence must be versioned within the repository under:
- `docs/` (e.g., `docs/v2.1/`, `docs/v2.2/`, `docs/releases/`)
- `artifacts/` (e.g., `artifacts/v2.1/`)

---

## 4. Immutability & Provenance Invariants

1. **Never delete or overwrite stable tags**: Once a tag `vX.Y.Z` is published, it is permanent.
2. **Never move published RC tags**: Once `vX.Y.Z-rcN` is published, its tag target commit is immutable.
3. **Never force-push release history**: Git history for release branches and release tags must remain append-only.
4. **Binary Alteration Policy**: If published binaries need changes for any reason, a new version or new release candidate (`-rc(N+1)`) must be created. Binaries must never be stealth-replaced under an existing tag.
