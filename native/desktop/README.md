# loci desktop shell

A Tauri 2 window around the console: on launch it starts the console server on
an ephemeral loopback port and points a native webview at it.

Same architecture as any local-first shell — the webview does not know or care
whether the page it loads would also work in a browser.

## What it does

- starts the console server (offline demo corpus on first run)
- picks a free port itself, so two instances never collide
- native window 1180×780 (min 860×560), titled "loci"

## Build

```bash
cargo build --release -p loci-desktop      # from native/
./target/release/loci-desktop
```

Requires the Rust toolchain (see native/README.md for the macOS SDK note).
Windows needs the WebView2 runtime — preinstalled on Windows 10/11.

## Packaging

```bash
cargo tauri build                          # .app + .dmg (macOS)
cargo tauri build --target x86_64-pc-windows-msvc   # .msi (Windows, on Windows)
```

Signing/notarization is not configured yet — unsigned builds work locally and
trigger the usual Gatekeeper/SmartScreen prompts on first launch.
