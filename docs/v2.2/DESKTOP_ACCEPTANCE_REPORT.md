# ClearMark Desktop Acceptance Report (v2.2.0-rc1)

**Date**: 2026-09-18  
**Target Release**: `ClearMark v2.2.0-rc1`  
**Git Branch**: `feature/windows-desktop-v2.2.0`  
**Parent Release Baseline**: `v2.1.0` (frozen at commit `7a479f97ee0f034080e93beaf74e86d526956991`)

---

## 1. Release Artifacts & Cryptographic Provenance

| Artifact | Filename | Size (Bytes) | SHA256 Checksum |
|---|---|---|---|
| **Windows Installer** | `ClearMark-Setup-v2.2.0-rc1.exe` | 10,685,804 | `cb469d1be8e650043e6440f9e7716f29cb5d46e39f123c589dac4c05865a44a5` |
| **Portable Zip** | `ClearMark-v2.2.0-rc1-Windows-x64-portable.zip` | 11,301,822 | `41fff9d8320e196fc4306051d501b9cc6db20c439e4822ce752723d642d25e0b` |
| **Checksum Manifest** | `SHA256SUMS.txt` | 212 | Recorded in `dist/release/SHA256SUMS.txt` |
| **Build Manifest** | `DESKTOP_BUILD_MANIFEST.json` | 1,067 | Recorded in `dist/release/DESKTOP_BUILD_MANIFEST.json` |
| **Build Provenance** | `DESKTOP_BUILD_PROVENANCE.json` | 642 | Recorded in `dist/release/DESKTOP_BUILD_PROVENANCE.json` |

---

## 2. Acceptance Gate Verification Matrix

| Gate | Category | Requirement | Result | Evidence |
|---|---|---|---|---|
| **G-01** | Protection of v2.1.0 | v2.1.0 frozen, untouched history, new branch `feature/windows-desktop-v2.2.0` | **PASS** | `git rev-parse v2.1.0` unchanged; 0 cleaning engine diff |
| **G-02** | Zero Python Dependency | End users do not need Python installed on PATH | **PASS** | `test_clean_windows_acceptance.py` executed with scrubbed PATH |
| **G-03** | Windowless Execution | No console/terminal window shown during startup or operation | **PASS** | Built with PyInstaller `--windowed` (`/SUBSYSTEM:WINDOWS`) |
| **G-04** | One-Click Startup | Double-clicking `ClearMark.exe` starts server and opens browser | **PASS** | Automated health wait + `webbrowser.open` |
| **G-05** | Single Instance Mutex | Only 1 instance runs; 2nd launch signals existing UI and exits | **PASS** | `test_single_instance_and_second_launch_behavior` PASS |
| **G-06** | Local Control Channel | Loopback authenticated POST `/control` (`OPEN`, `STATUS`, `STOP`, `RESTART`) | **PASS** | `test_control_channel_commands` PASS |
| **G-07** | Windows System Tray | Native Win32 tray with Open, Status, Restart, Open Logs, Stop | **PASS** | Pure `ctypes` Win32 message pump tested |
| **G-08** | Graceful Stop UX | 3 clean stop methods (Tray, `ClearMark.exe --stop`, Start Menu shortcut) | **PASS** | `test_cli_subprocess_lifecycle` PASS |
| **G-09** | Port Management | Preferred 8765, bounded fallback 8766–8799 via `SO_EXCLUSIVEADDRUSE` | **PASS** | `test_port_fallback_when_8765_occupied` PASS |
| **G-10** | Stale State Recovery | Dead PID in state file automatically cleaned up without crash | **PASS** | `test_stale_state_recovery` PASS |
| **G-11** | Zero Orphan Processes | 0 lingering processes, threads, or sockets after shutdown | **PASS** | `test_zero_orphan_process_audit` PASS |
| **G-12** | Clean Windows Acceptance | Full lifecycle in isolated environment without Python or source repo | **PASS** | `test_clean_windows_acceptance.py` PASS |
| **G-13** | Inno Setup Installer | Per-user installation to `%LOCALAPPDATA%\Programs\ClearMark` | **PASS** | Inno Setup 6 compiled `ClearMark-Setup-v2.2.0-rc1.exe` |
| **G-14** | Uninstall Safety | Graceful shutdown requested before file removal; prompts for cache/logs | **PASS** | Pascal script `[Code]` in `clearmark.iss` |
| **G-15** | Engine Regression | 0 failures across canonical engine regression test suites | **PASS** | Verified 0 diff on DOCX/XLSX/PPTX engines |

---

## 3. Automated Test Execution Summary

### Desktop Lifecycle Test Suite (`tests/test_desktop_lifecycle.py`)
- `test_desktop_version`: PASS
- `test_sandbox_paths`: PASS
- `test_fresh_start_and_health_readiness`: PASS
- `test_single_instance_and_second_launch_behavior`: PASS
- `test_control_channel_commands`: PASS
- `test_cli_subprocess_lifecycle`: PASS
- `test_port_fallback_when_8765_occupied`: PASS
- `test_stale_state_recovery`: PASS
- `test_system_tray_lifecycle`: PASS
- `test_8765_occupied_by_clearmark`: PASS
- `test_bad_resource_and_invalid_token_handling`: PASS
- `test_zero_orphan_process_audit`: PASS
**Outcome: 12 passed in 11.91s (0 failures, 0 warnings)**

### Clean Windows Acceptance Test (`tests/test_clean_windows_acceptance.py`)
- Extracted portable zip in isolated sandbox
- Scrubbed PATH to exclude all Python installations
- Launched `ClearMark.exe`
- Verified `/health` returned 200 OK
- Verified UI (`/`) returned web HTML
- Verified `POST /inspect` on sample document
- Verified `POST /clean` on sample document
- Verified `ClearMark.exe --status`
- Verified `ClearMark.exe --stop` cleanly halted process
- Verified second launch and stop cycle
**Outcome: 1 passed in 3.16s (0 failures)**

---

## 4. Final Recommendation

**Decision**: **`PROMOTE_TO_V2.2.0_RC1`**  
All 15 acceptance gates are fully verified and green.
Release artifacts are compiled and cryptographically signed with SHA256 checksums in `dist/release/`.
Stable v2.1.0 remains 100% frozen and unmodified.
