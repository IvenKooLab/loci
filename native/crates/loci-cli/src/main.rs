//! `loci` — Q&A over a personal knowledge base, native build.

use std::path::PathBuf;
use std::process::ExitCode;

use anyhow::Result;
use clap::{Parser, Subcommand};
use loci_core::config::Config;
use loci_core::embed::{EmbedConfig, Embedder, HttpEmbedder};
use loci_core::indexer::ingest;
use loci_core::retriever::{Filters, RetrievalConfig, Retriever};
use loci_core::store::Store;

#[derive(Parser)]
#[command(name = "loci", version, about = "Q&A over your personal knowledge base")]
struct Cli {
    /// config file
    #[arg(long, global = true, default_value = "config.toml")]
    config: PathBuf,

    /// override the store path
    #[arg(long, global = true)]
    db: Option<PathBuf>,

    /// run without any network: deterministic hash embedder, BM25-only ranking
    #[arg(long, global = true)]
    offline: bool,

    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    /// scan sources and index new or changed files
    Ingest {
        /// re-embed everything, ignoring content hashes
        #[arg(long)]
        force: bool,
    },
    /// retrieval only — ranked excerpts with path > section breadcrumbs
    Search {
        query: String,
        #[arg(long)]
        tag: Option<String>,
        #[arg(long = "in", value_name = "PATH")]
        path_contains: Option<String>,
        #[arg(short = 'k', long)]
        k: Option<usize>,
    },
    /// what is in the index
    Stats,
    /// check config, index and embedding endpoint
    Doctor,
    /// the web console, served by this binary
    Gui {
        /// corpus / index directory (default: the bundled demo corpus)
        #[arg(long)]
        dir: Option<PathBuf>,
        /// port to listen on
        #[arg(long, default_value_t = 8790)]
        port: u16,
    },
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    match run(cli) {
        Ok(code) => code,
        Err(e) => {
            eprintln!("loci: {e:#}");
            ExitCode::FAILURE
        }
    }
}

fn open_store(cfg: &Config, override_path: Option<PathBuf>) -> Result<Store> {
    let path = override_path.unwrap_or_else(|| cfg.store_path());
    Store::open(path)
}

fn embedder_for(cfg: &Config, offline: bool) -> Result<Box<dyn Embedder>> {
    if offline {
        return Ok(Box::new(loci_core::embed::HashEmbedder::default()));
    }
    if cfg.embed.api_key.is_empty() {
        anyhow::bail!(
            "embed.api_key is not set — config.toml or BRAIN_EMBED_API_KEY\n\
             (for an offline tour of the pipeline, use `loci demo` in the desktop app)"
        );
    }
    let cfg_embed = EmbedConfig {
        base_url: cfg.embed.base_url.clone(),
        api_key: cfg.embed.api_key.clone(),
        model: cfg.embed.model.clone(),
        batch: 16,
    };
    Ok(Box::new(HttpEmbedder::new(cfg_embed)?))
}

fn run(cli: Cli) -> Result<ExitCode> {
    let cfg = Config::load(&cli.config)?;

    match cli.cmd {
        Cmd::Ingest { force } => {
            let problems = cfg.validate();
            if !problems.is_empty() {
                anyhow::bail!("missing configuration:\n  {}", problems.join("\n  "));
            }
            let mut store = open_store(&cfg, cli.db)?;
            let embedder = embedder_for(&cfg, cli.offline)?;
            let report = ingest(&cfg, &mut store, embedder.as_ref(), force)?;
            for gone in &report.pruned {
                println!("  - pruned (file gone): {gone}");
            }
            println!(
                "Done{}: {} added / {} updated / {} skipped — {} chunks in store",
                if force { " (forced)" } else { "" },
                report.added,
                report.updated,
                report.skipped,
                store.count()?
            );
            if report.reused_vectors > 0 {
                println!("  reused {} embeddings", report.reused_vectors);
            }
            Ok(ExitCode::SUCCESS)
        }

        Cmd::Search { query, tag, path_contains, k } => {
            let store = open_store(&cfg, cli.db)?;
            let embedder = embedder_for(&cfg, cli.offline)?;
            let rcfg = RetrievalConfig {
                top_k: cfg.retrieval.top_k,
                hybrid: cfg.retrieval.hybrid && !cli.offline,
                // --offline has no meaningful embeddings: rank by BM25 alone
                lexical_only: cli.offline,
                rrf_k: cfg.retrieval.rrf_k,
                tokenizer: cfg.tokenizer(),
                fetch_factor: 4,
            };
            let mut retriever = Retriever::new(&store, embedder.as_ref(), rcfg);
            let filters = Filters { tag, path_contains, since: None };
            let hits = retriever.search(&query, &filters, k)?;
            if hits.is_empty() {
                println!("(no results)");
                return Ok(ExitCode::SUCCESS);
            }
            for (i, h) in hits.iter().enumerate() {
                let where_ = if h.section.is_empty() {
                    h.source.clone()
                } else {
                    format!("{} > {}", h.source, h.section)
                };
                let sim = match h.distance {
                    Some(d) => format!("similarity {:.3}", 1.0 - d),
                    None => "bm25 hit".to_string(),
                };
                println!("[{}] {}  ({})", i + 1, where_, sim);
                let preview: String = h.text.chars().take(160).collect();
                println!("    {}...", preview.replace('\n', " "));
            }
            Ok(ExitCode::SUCCESS)
        }

        Cmd::Stats => {
            let store = open_store(&cfg, cli.db)?;
            println!("store      : {}  ({} chunks)", store.path().display(), store.count()?);
            println!(
                "models     : {} (embed) / {} (llm)",
                cfg.embed.model, cfg.llm.model
            );
            println!(
                "retrieval  : hybrid {} (rrf_k={}), top_k={}, tokenizer={}",
                if cfg.retrieval.hybrid { "on" } else { "off" },
                cfg.retrieval.rrf_k,
                cfg.retrieval.top_k,
                cfg.bm25.tokenizer
            );
            let per = store.per_source()?;
            if per.is_empty() {
                println!("sources    : (index is empty — run `loci ingest` first)");
                return Ok(ExitCode::SUCCESS);
            }
            let mut rows: Vec<_> = per.into_iter().collect();
            rows.sort_by(|a, b| a.0.cmp(&b.0));
            let width = rows.iter().map(|(p, _)| p.len()).max().unwrap_or(0);
            println!("sources    :");
            for (path, n) in rows {
                println!("  {path:<width$}  {n:>5} chunks");
            }
            Ok(ExitCode::SUCCESS)
        }

        Cmd::Gui { dir, port } => {
            let root = dir.unwrap_or_else(|| std::env::current_dir().unwrap_or_default().join("loci-demo-notes"));
            loci_cli::console::serve(root, port, cfg, cli.offline).map(|_| ExitCode::SUCCESS)
        }


        Cmd::Doctor => {
            let mut failed = 0usize;
            let mut say = |ok: Option<bool>, name: &str, detail: &str| {
                let mark = match ok {
                    Some(true) => '✓',
                    Some(false) => {
                        failed += 1;
                        '✗'
                    }
                    None => 'i',
                };
                println!("  {mark} {name:<16} {detail}");
            };

            say(
                Some(cli.config.exists()),
                "config file",
                if cli.config.exists() {
                    "found"
                } else {
                    "missing (copy config.example.toml to config.toml)"
                },
            );
            say(
                Some(!cfg.embed.api_key.is_empty()),
                "embed key",
                if cfg.embed.api_key.is_empty() { "missing" } else { "configured" },
            );
            say(
                Some(!cfg.sources.is_empty()),
                "sources",
                &format!("{} directories", cfg.sources.len()),
            );
            match loci_core::Tokenizer::from_name(&cfg.bm25.tokenizer) {
                Some(_) => say(Some(true), "tokenizer", &cfg.bm25.tokenizer),
                None => say(
                    Some(false),
                    "tokenizer",
                    &format!("unknown {:?}", cfg.bm25.tokenizer),
                ),
            }

            let store = open_store(&cfg, cli.db)?;
            say(
                Some(true),
                "store",
                &format!("{} chunks at {}", store.count()?, store.path().display()),
            );

            if !cfg.embed.api_key.is_empty() {
                match embedder_for(&cfg, cli.offline).and_then(|e| e.embed(&["ping".to_string()])) {
                    Ok(v) => say(
                        Some(true),
                        "embed endpoint",
                        &format!("reachable, dim={}", v.first().map(|x| x.len()).unwrap_or(0)),
                    ),
                    Err(e) => say(Some(false), "embed endpoint", &format!("{e:#}")),
                }
            }

            println!("\nloci {} · {}", env!("CARGO_PKG_VERSION"), std::env::consts::OS);
            Ok(if failed == 0 {
                ExitCode::SUCCESS
            } else {
                ExitCode::FAILURE
            })
        }
    }
}

