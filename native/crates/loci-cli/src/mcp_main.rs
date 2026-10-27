//! `loci-mcp` — the MCP server over stdio.
//!
//! This is loci's primary interface: mount it in Claude Desktop, Cursor, Cline
//! or any other MCP host and the assistant gets the whole knowledge base as
//! tools. The console and a desktop shell are alternate front-ends to the same
//! index, never a requirement.

use std::io::{self, BufReader};

use anyhow::{Context, Result};
use loci_core::config::Config;
use loci_core::mcp;

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let mut config_path = std::path::PathBuf::from("config.toml");
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--config" | "-c" => {
                if let Some(p) = args.next() {
                    config_path = std::path::PathBuf::from(p);
                }
            }
            "--version" | "-V" => {
                println!("loci-mcp {}", env!("CARGO_PKG_VERSION"));
                return Ok(());
            }
            other => {
                eprintln!("loci-mcp: unknown argument {other:?}\n\
                           usage: loci-mcp [--config PATH]");
                std::process::exit(2);
            }
        }
    }

    let cfg = Config::load(&config_path)
        .with_context(|| format!("load {}", config_path.display()))?;
    let mut server = mcp::from_config(cfg)?;

    // stdout is the protocol stream: diagnostics go to stderr only
    let stdin = io::stdin();
    let stdout = io::stdout();
    server
        .serve(BufReader::new(stdin.lock()), stdout.lock())
        .context("mcp serve loop")
}
