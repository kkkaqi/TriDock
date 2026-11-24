# Runtime import wizard implementation plan

**Goal:** Make image-free system onboarding discover and validate compatible local environments before instance creation.

**Architecture:** Add an independent inspector/archive module, expose bounded inspection/extraction/boot-probe operations over existing IPC, and use the current form as a progressive wizard. Keep legacy instance records usable.

**Tech Stack:** Python standard library, Electron isolated preload, existing renderer CSS/JS.

## Constraints

- No automatic runtime/image downloads or execution during inspection.
- No arbitrary generic image compatibility claims; unknown versions remain unknown.
- ZIP expands only after the user chooses a destination, never overwriting external data.
- Preserve existing instances and original IPA functionality.

## Tasks

- [x] Add tests/test_runtime_inspector.py. Cover platform and nested-root detection, Android AVD configuration discovery, required binaries/images, host/disk checks, ZIP traversal/link/duplicate/ratio rejection and external-file preservation. Run these tests to failing before adding the module.
- [x] Implement runtime_inspector.py with inspect_environment(values), inspect_archive(path), extract_environment(path, destination), host_info(). Structured results must distinguish blocking errors, warnings and values that remain unverified.
- [x] Extend SystemManager create/start and IPC to apply inspection on guided creations and recheck verified records before launch. Add device-probe action that does not implicitly boot. Preserve old record compatibility.
- [x] Update system form with support profiles, source selection, inspect/extract controls, detected AVD selector, check results, stale-input invalidation, create and try-start actions. Update smoke to check wizard creation from synthetic fixtures.
- [x] Run Python suite, source and packaged Electron smoke, inspect UI screenshots, build 0.4.0 and verify installer resources contain no guest images. Record concrete limits in README; commit changes on feature branch.

## Verification

2026-11-24: 53 Python tests passed. Source desktop smoke and packaged application smoke passed. The packaged test exercises archive inspection and extraction, nested runtime discovery, check gating, stale-input invalidation, source-path reset, guided creation, HAP drop, native shortcut creation and minimum-width layout, using synthetic files without executing them. NSIS 0.4.0 built successfully (126.4 MiB). Source and bundled Python modules match. ASAR and resources contain no guest images or application packages. Reviewer findings about writable AVD volume, stale iOS work paths, extraction timeout and iOS helper dependencies were corrected. Real guest boot, app compatibility and performance remain unverified. Android requires an existing AVD; iOS requires prior ASoftware deployment; ZIP imports never auto-deploy an OS.
