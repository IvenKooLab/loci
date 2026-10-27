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
    /// offline tour over a bundled sample corpus (no key, no network)
    Demo {
        #[arg(long)]
        dir: Option<PathBuf>,
        #[arg(short = 'k', long)]
        k: Option<usize>,
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

fn embedder_for(cfg: &Config) -> Result<Box<dyn Embedder>> {
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
            let embedder = embedder_for(&cfg)?;
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
            let embedder = embedder_for(&cfg)?;
            let rcfg = RetrievalConfig {
                top_k: cfg.retrieval.top_k,
                hybrid: cfg.retrieval.hybrid,
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
                    None => "hybrid hit".to_string(),
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

        Cmd::Demo { dir, k } => demo(dir, k),

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
                match embedder_for(&cfg).and_then(|e| e.embed(&["ping".to_string()])) {
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

/// A tour that works before anyone has an API key: six fictional notes,
/// chunked and ranked with the real pipeline, using the offline hash embedder.
fn demo(dir: Option<PathBuf>, k: Option<usize>) -> Result<ExitCode> {
    use loci_core::embed::HashEmbedder;

    let root = dir.unwrap_or_else(|| std::env::current_dir().unwrap_or_default().join("loci-demo-notes"));
    std::fs::create_dir_all(&root)?;
    for (name, body) in DEMO_NOTES {
        let path = root.join(name);
        if !path.exists() {
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::fs::write(&path, body)?;
        }
    }

    let mut cfg = Config::default();
    cfg.sources.push(loci_core::config::SourceConfig {
        path: root.to_string_lossy().to_string(),
        chunk_size: None,
        chunk_overlap: None,
    });
    let db = root.join(".index.db");
    let _ = std::fs::remove_file(&db);
    let mut store = Store::open(&db)?;
    let embedder = HashEmbedder::default();
    let report = ingest(&cfg, &mut store, &embedder, false)?;

    println!("loci demo — a tour of a small sample knowledge base\n");
    println!("  corpus    {}", root.display());
    println!("  index     {} files · {} chunks", report.added, report.chunks);
    println!("  retrieval hybrid (vector + BM25) with the offline hash embedder");
    println!("            — no config, no key, no network\n");

    let rcfg = RetrievalConfig::default();
    let mut retriever = Retriever::new(&store, &embedder, rcfg);
    let queries = [
        "why did the humidity sensor replace the BME280?",
        "how long can the station run on one charge?",
    ];
    for (i, q) in queries.iter().enumerate() {
        println!("-- example {}/{} {}", i + 1, queries.len(), "-".repeat(40));
        let hits = retriever.search(q, &Filters::default(), k)?;
        for (n, h) in hits.iter().enumerate() {
            let where_ = if h.section.is_empty() {
                h.source.clone()
            } else {
                format!("{} > {}", h.source, h.section)
            };
            let preview: String = h.text.chars().take(120).collect();
            println!("  [{}] {}  ({:.2})", n + 1, where_, h.score);
            println!("      {}...", preview.replace('\n', " "));
        }
        println!();
    }
    println!("Next steps");
    println!("  loci ingest && loci search \"your question\"   index your own notes");
    println!("  loci doctor                                 check config and endpoint");
    Ok(ExitCode::SUCCESS)
}

const DEMO_NOTES: &[(&str, &str)] = &[
    ("projects/aurora/decisions.md", "# Aurora — decisions\n\n## ADR-001: SHT45 over BME280\n\nRevision A used a BME280. The balcony sits between 80% and 100% relative humidity for most of the winter, and the BME280 drifted upward by roughly 6% RH after two months. Decision: SHT45.\n"),
    ("projects/aurora/battery-budget.md", "# Aurora — power budget\n\nTarget: six months on one charge, sampling every five minutes. The MCU wake window dominates at 7.68 mAh/day; total draw is 9.52 mAh/day.\n"),
    ("projects/aurora/retro.md", "# Retro 2026-09-18\n\n## What did not\n\nWi-Fi reconnect storms cost 120 mAh over two days. The antenna drops to -78 dBm when the balcony door is closed.\n"),
    ("notes/reading-list.md", "# Reading list\n\n## Electronics\n\nThe Art of Electronics, chapter 9 on voltage references.\n"),
];
