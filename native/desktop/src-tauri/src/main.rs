// Prevents an extra console window on Windows in release builds
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpListener;
use tauri::{WebviewUrl, WebviewWindowBuilder};

fn main() {
    // find a free port before starting: the console prints its own URL but the
    // window must know it synchronously
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind ephemeral port");
    let port = listener.local_addr().expect("local addr").port();
    drop(listener);

    let root = std::env::current_dir()
        .unwrap_or_else(|_| std::path::PathBuf::from("."))
        .join("loci-demo-notes");

    // console server in a background thread: same code as `loci gui`
    std::thread::spawn(move || {
        let cfg = loci_core::config::Config::default();
        let _ = loci_cli::console::serve(root, port, cfg, true);
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
