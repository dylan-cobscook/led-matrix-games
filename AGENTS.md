# Project Instructions

## Architecture

- This is a CircuitPython project for an Adafruit Matrix Portal (ATSAMD51J19 with an ESP32 Wi-Fi co-processor) driving a 64×32 RGB LED matrix.
- `code.py` is the device firmware. It configures the SPI Wi-Fi connection and matrix display, then serves the browser app over HTTP. Its `/pixel` route accepts edits, `/pixels` returns a full snapshot, and `/updates` returns a full snapshot or versioned changes.
- `index.html` is a self-contained browser client. Its canvas mirrors the 64×32 matrix; its JavaScript draws pixels, posts edits, and polls for updates.
- `secrets.py` supplies the Wi-Fi credentials used by the firmware. Keep credentials private and do not commit them.
- The repository has no application subdirectories, dependency manifest, CI configuration, or test suite. `README.md` currently contains only a placeholder.

## Build and Test

- There is no repository-defined build or automated test command.
- For a host-side Python syntax check, run `python -m py_compile code.py` from the repository root. This does not check CircuitPython library availability or behavior on the board.
- Do not perform hardware testing. For firmware behavior changes, ask the user to validate on the Matrix Portal: confirm it boots, connects to Wi-Fi, serves the page, applies a pixel edit, and synchronizes edits between browser clients.
- No deployment procedure is documented here. Do not assume a particular flashing, file-copy, or library-install workflow; ask for the project’s established procedure if deployment details are needed.

## Coding Conventions

- Keep firmware compatible with CircuitPython and the board’s available libraries; do not assume desktop-only Python packages or services.
- Keep the device and browser dimensions aligned at 64 columns by 32 rows.
- Preserve the HTTP contract between `code.py` and `index.html`, including coordinate and color validation, full-snapshot and delta response formats, and cache behavior.
- Follow the existing simple style: `snake_case` for Python functions and variables, uppercase names for constants, and self-contained HTML/CSS/JavaScript without a frontend build toolchain.
- Keep device memory use bounded. Reuse the bounded pixel-update history pattern rather than retaining an unbounded log.
- This is a demo for students who are learning about coding. Comment the code to explain the purpose of each function and the meaning of each variable. Avoid complex or clever code that is hard to read.

## Completing a Change

- When first getting a new identified issue or feature request, develop a plan for the change and discuss it with the user before implementing it. Make sure the plan includes relevant details, but avoid being overly verbose. Assume the user has a basic understanding of Python and the codebase, but explain any complex concepts. Avoid making large changes without prior discussion.
- Trace changes across both firmware and browser code when they affect display state or the HTTP protocol.
- Check the Python syntax. For behavior changes, ask the user to run the on-device/browser smoke test and report the result; do not attempt hardware validation.
- Keep credentials and other local-only configuration out of commits. Do not overwrite a developer’s local `secrets.py`.
- Update these instructions if the repository gains a documented deployment process, build/test tooling, or a different hardware target.
