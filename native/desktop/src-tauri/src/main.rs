// Prevents an extra console window on Windows in release builds
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpListener;
use tauri::{WebviewUrl, WebviewWindowBuilder};

fn main() {
    // find a free port before starting: the console prints its own URL but the
    // window must know it synchronously
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind ephemeral port");
    let port = listener.local_addr().expect("local addr").port();

    // Anchor the demo notes to the executable, not the caller's cwd. Launching
    // the .app from Finder/Dock gives an arbitrary cwd (often /), and relative
    // paths silently pointed at the wrong place — or nowhere.
    let root = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|p| p.to_path_buf()))
        .unwrap_or_else(|| std::path::PathBuf::from("."))
        .join("loci-demo-notes");

    // Keep the listener we bound: dropping it before the server binds again is
    // a TOCTOU race that can lose the port to another process. serve_bound owns
    // the already-reserved socket.
    std::thread::spawn(move || {
        let cfg = loci_core::config::Config::default();
        let _ = loci_cli::console::serve_bound(root, listener, cfg, true);
    });

    tauri::Builder::default()
        .setup(move |app| {
            let url = format!("http://127.0.0.1:{port}/ui");
            WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::External(url.parse().expect("valid url")),
            )
            .title("loci")
            .inner_size(1180.0, 780.0)
            .min_inner_size(860.0, 560.0)
            .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
