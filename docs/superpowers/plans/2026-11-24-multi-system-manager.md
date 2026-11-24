# Multi-system Manager Implementation Plan

**Goal:** Add an image-free Windows manager for Android, iOS and OpenHarmony environments and their application packages.

**Architecture:** Keep the legacy library intact. A separate SQLite-backed manager exposes validated provider operations through the existing isolated Electron IPC bridge. The renderer adds an instance page with external-environment setup and per-instance packages.

**Tech Stack:** Python standard library, Electron, existing HTML/CSS/JavaScript.

## Global Constraints

- No guest images or guest engines in the installer; no automatic image downloads or copies.
- Preserve existing IPA functionality and unrelated files.
- Only known runtime entry points; explicit device selection; no user-entered shell commands.
- Removing a record never deletes external runtime or application files.
- Report real verification limits for iOS/OpenHarmony.

## Execution

- [x] Add tests in tests/test_system_manager.py for empty state, directory validation, duplicate runtime targets, persistence, cross-platform package rejection, bounded archive parsing and isolated transport commands. Run `python -m unittest discover -s tests -v` and observe new tests fail before implementing.
- [x] Add system_manager.py: SQLite instances/packages, provider validation, external-file references, package inspection, process ownership, start/stop/install/launch/log operations. Run the same tests to green.
- [x] Extend desktop_bridge.py action choices and electron/main.cjs/preload.cjs IPC with explicit operations and native directory/file dialogs. Include system_manager.py in electron-builder.yml.
- [x] Extend electron/renderer/index.html, app.js and app.css with system navigation, empty state, platform-specific creation form, runtime help links, resource fields, instance state, logs, app import and launch. Preserve old library smoke assertions.
- [x] Extend Electron smoke verification for initial system page, platform form switching and navigation. Run `npm run test:desktop`, Python tests, Node syntax checks and inspect a captured UI image.
- [x] Document provider prerequisites/compatibility and use `npm run build:win` to generate an installer with only host application files. Review diff, packaged Python resources and archive contents before reporting results.

## Verification record

2026-11-24: 32 Python tests passed. Source Electron navigation and platform-form smoke passed. Packaged Electron using bundled Python created a synthetic OpenHarmony instance and imported a HAP via drag/drop. NSIS build succeeded (126.4 MiB). ASAR and resource checks found no guest image/app packages. Source and bundled system_manager.py are identical. Real guest boot/install/performance acceptance remains unverified; no guest image was downloaded. iOS modern apps still open from the guest desktop, and only one ASoftware instance can run at a time.
