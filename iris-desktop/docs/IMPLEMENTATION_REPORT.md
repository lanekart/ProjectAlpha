# IRIS Desktop V1 Implementation Report

## Architecture Selected

IRIS now has an additive desktop application scaffold in `iris-desktop`.

- Tauri 2 provides the installed desktop shell, transparent frameless window, tray/menu bar, native app commands, app data storage, native speech, and auto-start integration.
- React and TypeScript provide the animated robot, compact command panel, settings panel, confirmation UI, and deterministic client-side state model.
- No FastAPI or WebSocket server was retained for V1. The first desktop version is single-device and uses Tauri commands for local functionality. A Python sidecar can be added later only for existing Project Alpha intelligence that genuinely needs Python.
- The shared domain logic is separated from the robot UI so future mobile clients can reuse command policy, integration status, and briefing behavior.

## Transparent Robot Window

The main Tauri window is configured as transparent, frameless, non-resizable, always on top, and skipped from the taskbar. The React surface keeps the body transparent and renders the robot plus optional adjacent panels. The robot has state-driven CSS animations for idle, listening, thinking, speaking, success, error, sleep, and quiet states.

## Tray and Background Operation

The Tauri process owns a tray/menu-bar icon with Restore IRIS, Pause Listening, Do Not Disturb, and Quit IRIS actions. Hiding the robot hides only the visible window; the process remains alive for background tasks and command execution. Restore emits an event back to the UI to synchronize robot state.

## Application Security

Application control is allowlist based. Opening approved apps is immediate. Closing apps is routed through confirmation unless an app is explicitly safe to close. Arbitrary shell execution, file deletion, email sending, computer shutdown, and financial trading are blocked in the typed policy model.

## Current macOS Coverage

- Transparent always-on-top robot window.
- Menu-bar tray actions.
- Approved app opening through controlled `open -a` calls.
- Graceful close requests through controlled AppleScript against approved bundle names.
- Native text-to-speech through `say`.

## Current Windows Coverage

- Transparent always-on-top robot window configuration.
- System tray actions.
- Approved app opening through known executable names.
- Graceful close requests through `taskkill /im` without force.
- Native text-to-speech through Windows speech synthesis.

## Known Limitations

- Rust/Cargo is not installed in this environment, so Tauri compilation and installer packaging were not run here.
- Push-to-talk is intentionally scaffolded and currently returns a clear permission/capability message; text commands work without microphone permission.
- Google Calendar and Gmail providers are represented by typed states and honest disconnected reporting, but OAuth adapters and secure credential storage are not implemented yet.
- Project Alpha app launching requires a configured path before it can run.
- Force-close is deliberately not exposed in the V1 UI.

## Test and Build Results

- Frontend tests: passed with 16 deterministic tests.
- TypeScript type checking: passed with `tsc --noEmit`.
- Frontend production build: passed with Vite.
- Rust formatting and linting: not run because `rustfmt` is not installed.
- Rust tests: not run because `cargo` is not installed.
- macOS Tauri package build: blocked because `tauri build` cannot run `cargo metadata`.
- Windows package build: not run in this macOS-oriented environment and also requires Cargo.
- Python tests: not run for this milestone because no Python sidecar was retained.

## Launching a Development Build

From `iris-desktop`:

1. Install dependencies with `npm install`.
2. Install the Rust toolchain and Tauri prerequisites for the target OS.
3. Run `npm run tauri dev` for local desktop development.
4. Build macOS artifacts with `npm run build:mac`.
5. Build Windows artifacts on Windows with `npm run build:windows`.

The app should be launched from the Tauri app icon or generated installer artifact; no backend server needs to be started manually.
