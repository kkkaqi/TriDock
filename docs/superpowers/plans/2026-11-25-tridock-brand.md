# TriDock branding implementation plan

**Goal:** Rename the desktop product and ship a new scalable three-window icon without losing user data.

**Architecture:** Keep persistent identifiers and data paths stable. Change display/packaging names, generate icon assets from a committed SVG, and use those assets consistently across the UI and Windows resources.

- [x] Add SVG source and deterministic Electron icon rasterizer, producing 1024 PNG and 16–256 ICO frames; visually inspect at desktop and toolbar sizes.
- [x] Update package metadata/version, Electron/Tk titles, Python user-facing messages, shortcut naming, new TriDock.cmd launcher and README. Preserve appId, protocol, historical root and old launcher compatibility.
- [x] Add branding regression assertions to desktop smoke; run Python and Electron tests.
- [x] Build TriDock 0.4.1 NSIS package, test packaged workflow and verify executable icon resources and backend files. Commit and deliver installer.

## Verification

2026-11-25: 55 Python tests passed; source and packaged Electron workflow smoke passed including new title assertions. EXE FileVersionInfo reports TriDock（三栖） / 0.4.1. Icons extracted from both TriDock.exe and the NSIS installer match the new three-window design by visual inspection. Seven ICO frames cover 16, 24, 32, 48, 64, 128 and 256 pixels. The SVG and PNG were visually inspected. Installer: dist/TriDock-0.4.1-win-x64-Setup.exe. Legacy appId, scheme, Python library root and Electron profile directory preserved.
