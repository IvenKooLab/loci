//! `loci gui` — the real console frontend, served by the native binary.
//!
//! The frontend (index.html / app.js / style.css) is byte-for-byte the same one
//! the Python build serves; this module implements the API surface it already
//! speaks, so the UI is identical and the backend is pure Rust.
//!
//! Tabs whose backend features are not ported yet (Harnesses, the memory graph)
//! render the console's own empty states — the frontend was built to degrade
//! like that, so nothing here fakes data.
//!
//! Loopback-only, anonymous admin — same trust model as the Python build.

use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use anyhow::{Context as _, Result};
use base64::Engine as _;
use serde_json::{json, Value};

use loci_core::chunker::{self, ChunkParams};
use loci_core::config::Config;
use loci_core::embed::{EmbedConfig, Embedder, HashEmbedder, HttpEmbedder};
use loci_core::indexer::ingest;
use loci_core::loader::{self, load_one};
use loci_core::retriever::{Filters, RetrievalConfig, Retriever};
use loci_core::store::Store;

// one source of truth: the frontend lives in the Python build's web dir, and
// both servers serve the same bytes — the two UIs cannot drift apart
const INDEX_HTML: &str = include_str!("../../../../src/loci/web/index.html");
const APP_JS: &str = include_str!("../../../../src/loci/web/app.js");
const STYLE_CSS: &str = include_str!("../../../../src/loci/web/style.css");

const SYSTEM_PROMPT: &str = "You are a Q&A assistant over the user's personal knowledge base. \
Answer only from the provided excerpts; if they don't contain the answer, say so plainly — \
do not invent. End your reply with a list of citations in the form [source: file path > section].";

const RING: usize = 500;
const UPLOAD_MAX_BYTES: usize = 16 << 20;

pub struct ConsoleState {
    pub root: PathBuf,     // corpus root (shown in /sources via cfg)
    pub memories: PathBuf, // memory notes
    pub uploads: PathBuf,  // uploaded documents
    pub db: PathBuf,       // index file
    pub cfg: Config,
    pub offline: bool,
    queries: Mutex<VecDeque<Value>>,
    audit: Mutex<VecDeque<Value>>,
}

fn now_str() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format!("{:02}:{:02}", (secs / 3600) % 24, (secs / 60) % 60)
}

impl ConsoleState {
    /// The embedder this instance runs with: the real endpoint when a key is
    /// configured, the deterministic offline one otherwise.
    fn embedder(&self) -> Arc<dyn Embedder> {
        if self.offline || self.cfg.embed.api_key.is_empty() {
            Arc::new(HashEmbedder::default())
        } else {
            match HttpEmbedder::new(EmbedConfig {
                base_url: self.cfg.embed.base_url.clone(),
                api_key: self.cfg.embed.api_key.clone(),
                model: self.cfg.embed.model.clone(),
                batch: 16,
            }) {
                Ok(e) => Arc::new(e),
                Err(_) => Arc::new(HashEmbedder::default()),   // fail open
            }
        }
    }

    /// Where harness logos live. Resolved against the corpus root so a fresh
    /// instance finds its own icons without a config entry.
    fn icons_dir(&self) -> PathBuf {
        let configured = self.cfg.http.icons.trim();
        if !configured.is_empty() {
            let p = PathBuf::from(configured);
            return if p.is_absolute() { p } else { self.root.join(p) };
        }
        self.root.join("icons")
    }

    fn retrieval_config(&self) -> RetrievalConfig {
        RetrievalConfig {
            top_k: self.cfg.retrieval.top_k,
            hybrid: self.cfg.retrieval.hybrid && !self.offline,
            // offline has no meaningful embeddings: rank by BM25 alone
            lexical_only: self.offline,
            rrf_k: self.cfg.retrieval.rrf_k,
            tokenizer: self.cfg.tokenizer(),
            fetch_factor: 4,
        }
    }

    fn log_query(&self, mut item: Value) {
        if let Some(o) = item.as_object_mut() {
            o.entry("ts".to_string())
                .or_insert(json!(now_str()));
        }
        let mut q = self.queries.lock().expect("queries");
        q.push_front(item);
        q.truncate(RING);
    }

    fn log_audit(&self, action: &str, detail: &str) {
        let item = json!({
            "ts": now_str(), "label": "local", "role": "admin", "action": action,
            "detail": detail.chars().take(200).collect::<String>()
        });
        let mut a = self.audit.lock().expect("audit");
        a.push_front(item);
        a.truncate(RING);
    }
}

// ---- public entry -+

pub fn serve(root: PathBuf, port: u16, mut cfg: Config, offline: bool) -> Result<()> {
    std::fs::create_dir_all(&root)?;
    let memories = root.join("memories");
    let uploads = root.join("uploads");
    std::fs::create_dir_all(&memories)?;

    let db = root.join(".index.db");
    let store = Store::open(&db)?;

    let use_offline = offline || cfg.embed.api_key.is_empty();
    let embedder: Arc<dyn Embedder> = if use_offline {
        Arc::new(HashEmbedder::default())
    } else {
        Arc::new(HttpEmbedder::new(EmbedConfig {
            base_url: cfg.embed.base_url.clone(),
            api_key: cfg.embed.api_key.clone(),
            model: cfg.embed.model.clone(),
            batch: 16,
        })?)
    };

    if cfg.sources.is_empty() {
        seed_demo(&root);
        cfg.sources.push(loci_core::config::SourceConfig {
            path: root.to_string_lossy().to_string(),
            chunk_size: None,
            chunk_overlap: None,
        });
    }

    let report = ingest(&cfg, &mut Store::open(&db)?, embedder.as_ref(), false)?;
    let chunks_total = store.count()?;

    let url = format!("http://127.0.0.1:{port}/ui");
    println!("loci gui — {url}");
    println!(
        "  corpus {} · {} files · {} chunks (indexed)",
        root.display(),
        report.added,
        chunks_total
    );
    println!(
        "  retrieval {}",
        if use_offline {
            "keyword only (BM25) — offline demo corpus".to_string()
        } else {
            "hybrid (vector + BM25)".to_string()
        }
    );
    println!("  Ctrl-C 退出");

    let listener = TcpListener::bind(("127.0.0.1", port))
        .with_context(|| format!("cannot listen on 127.0.0.1:{port} — another instance may be running"))?;

    let state = Arc::new(ConsoleState {
        root,
        memories,
        uploads,
        db,
        cfg,
        offline: use_offline,
        queries: Mutex::new(VecDeque::new()),
        audit: Mutex::new(VecDeque::new()),
    });

    for stream in listener.incoming() {
        let Ok(mut stream) = stream else { continue };
        let state = Arc::clone(&state);
        std::thread::spawn(move || {
            let _ = handle(&state, &mut stream);
        });
    }
    Ok(())
}

fn seed_demo(root: &Path) {
    for (name, body) in DEMO_NOTES {
        let path = root.join(name);
        if !path.exists() {
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent).ok();
            }
            std::fs::write(&path, body).ok();
        }
    }
}

// ---- request handling -----------------------------------------------------

fn handle(state: &ConsoleState, stream: &mut TcpStream) -> std::io::Result<()> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut line = String::new();
    reader.read_line(&mut line)?;
    let first = line.clone();
    let method = first.split_whitespace().next().unwrap_or("").to_string();
    let target = first.split_whitespace().nth(1).unwrap_or("/").to_string();
    let (path, query) = match target.split_once('?') {
        Some((p, q)) => (p.to_string(), q.to_string()),
        None => (target, String::new()),
    };

    let mut length = 0usize;
    loop {
        let mut h = String::new();
        if reader.read_line(&mut h)? == 0 || h.trim().is_empty() {
            break;
        }
        if let Some(v) = h.to_lowercase().strip_prefix("content-length:") {
            length = v.trim().parse().unwrap_or(0);
        }
    }
    let cap = if path == "/upload" { 24 << 20 } else { 1 << 20 };
    if length > cap {
        return respond(stream, 413, "application/json",
                       &json!({"error": format!("body exceeds {} MiB", cap >> 20)}).to_string());
    }
    let mut body_bytes = vec![0u8; length];
    if length > 0 {
        reader.read_exact(&mut body_bytes)?;
    }
    let body: Value = serde_json::from_slice(&body_bytes).unwrap_or(json!({}));

    let started = Instant::now();
    let (status, ctype, body) = route(state, &method, &path, &query, body, started);
    let _ = respond_bytes(stream, status, &ctype, &body);
    Ok(())
}

fn respond_bytes(stream: &mut TcpStream, status: u16, ctype: &str,
                 body: &[u8]) -> std::io::Result<()> {
    let reason = if status == 200 { "OK" } else { "Not Found" };
    let head = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: {ctype}\r\nContent-Length: {}\r\nCache-Control: max-age=300\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(head.as_bytes())?;
    stream.write_all(body)?;
    stream.flush()
}

fn mime_for(name: &str) -> &'static str {
    match name.rsplit('.').next().unwrap_or("").to_ascii_lowercase().as_str() {
        "png" => "image/png",
        "svg" => "image/svg+xml",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        _ => "application/octet-stream",
    }
}

fn respond(stream: &mut TcpStream, status: u16, ctype: &str, body: &str) -> std::io::Result<()> {
    let reason = match status {
        200 => "OK", 400 => "Bad Request", 401 => "Unauthorized",
        403 => "Forbidden", 404 => "Not Found", 413 => "Payload Too Large",
        _ => "Error",
    };
    let head = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: {ctype}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(head.as_bytes())?;
    stream.write_all(body.as_bytes())?;
    stream.flush()
}

/// Query-string decoding: %XX escapes and '+' as space. A truncated escape
/// (e.g. "x%2") is kept literally rather than panicking.
fn urldecode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        match b[i] {
            b'%' if i + 2 < b.len() => {
                if let Ok(v) = u8::from_str_radix(&s[i + 1..i + 3], 16) {
                    out.push(v);
                    i += 3;
                    continue;
                }
                out.push(b'%');
            }
            b'+' => out.push(b' '),
            c => out.push(c),
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).to_string()
}

fn qmap(query: &str) -> Vec<(String, String)> {
    query
        .split('&')
        .filter(|s| !s.is_empty())
        .map(|pair| match pair.split_once('=') {
            Some((k, v)) => (k.to_string(), urldecode(v)),
            None => (urldecode(pair), String::new()),
        })
        .collect()
}

fn qget<'a>(q: &'a [(String, String)], key: &str) -> Option<&'a str> {
    q.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str())
}

fn route(state: &ConsoleState, method: &str, path: &str, query: &str,
         body: Value, started: Instant) -> (u16, String, Vec<u8>) {
    let q = qmap(query);
    match (method, path) {
        // harness logos: public and non-sensitive, but only a bare filename
        // from the configured icons dir — no path components, no traversal
        (_, p) if p.starts_with("/icons/") => {
            let name = p["/icons/".len()..]
                .rsplit('/')
                .next()
                .unwrap_or("")
                .to_string();
            let dir = state.icons_dir();
            let file = dir.join(&name);
            // disk wins (a user override), builtin logos are the fallback so a
            // fresh instance renders without copying any files
            let from_disk = if name.is_empty() { None } else {
                std::fs::read(&file).ok().filter(|_| file.is_file())
            };
            match from_disk.or_else(|| loci_core::assets::embedded_icon(&name).map(|b| b.to_vec())) {
                Some(bytes) if !name.is_empty() => (
                    200,
                    mime_for(&name).to_string(),
                    bytes.to_vec(),
                ),
                _ => (404, "application/json".into(),
                      json!({"error": "not found"}).to_string().into_bytes()),
            }
        }
        (_, "/ui") => (200, "text/html; charset=utf-8".into(), INDEX_HTML.into()),
        (_, "/ui/app.js") => (200, "application/javascript".into(), APP_JS.into()),
        (_, "/ui/style.css") => (200, "text/css".into(), STYLE_CSS.into()),

        (_, "/health") => (200, "application/json".into(), json!({
            "status": "ok",
            "version": env!("CARGO_PKG_VERSION"),
            "me": {"label": "local", "role": "admin"}
        }).to_string().into_bytes()),

        ("POST", "/search") => {
            let query = body.get("query").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let k = body.get("k").and_then(|v| v.as_u64()).map(|v| v as usize);
            let store = match Store::open(&state.db) {
                Ok(s) => s,
                Err(e) => return (500, "application/json".into(), json!({"error": format!("{e:#}")}).to_string().into_bytes()),
            };
            let embedder = state.embedder();
            let rcfg = state.retrieval_config();
            let mut r = Retriever::new(&store, embedder.as_ref(), rcfg);
            let filters = Filters {
                tag: body.get("tag").and_then(|v| v.as_str()).map(str::to_string),
                path_contains: body.get("in").and_then(|v| v.as_str()).map(str::to_string),
                since: None,
            };
            let hits = r.search(&query, &filters, k).unwrap_or_default();

            state.log_query(json!({
                "label": "local", "role": "admin", "kind": "search",
                "query": query.chars().take(300).collect::<String>(),
                "hits": hits.len(),
                "top": hits.first().map(citation).unwrap_or_default(),
                "ms": (started.elapsed().as_secs_f64() * 1000.0)
            }));

            let blocks: Vec<String> = hits.iter().enumerate().map(|(i, h)| {
                let where_ = citation(h);
                let text: String = h.text.chars().take(500).collect();
                format!("[{}] {}\n{}", i + 1, where_, text)
            }).collect();
            let result = if hits.is_empty() { "(no results)".to_string() } else { blocks.join("\n\n") };
            let hits_json: Vec<Value> = hits.iter().map(|h| json!({
                "source": h.source, "section": h.section, "text": h.text,
                "tags": h.tags, "distance": h.distance
            })).collect();
            (200, "application/json".into(), json!({"result": result, "hits": hits_json}).to_string().into_bytes())
        }

        ("POST", "/ask") => {
            let question = body.get("question").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let store = match Store::open(&state.db) {
                Ok(s) => s,
                Err(e) => return (500, "application/json".into(), json!({"error": format!("{e:#}")}).to_string().into_bytes()),
            };
            let embedder = state.embedder();
            let rcfg = state.retrieval_config();
            let mut r = Retriever::new(&store, embedder.as_ref(), rcfg);
            let hits = r.search(&question, &Filters::default(), None).unwrap_or_default();
            let text = llm_answer(&state.cfg, &question, &hits);
            state.log_query(json!({
                "label": "local", "role": "admin", "kind": "ask",
                "query": question.chars().take(300).collect::<String>(),
                "hits": hits.len(), "top": hits.first().map(citation).unwrap_or_default(),
                "ms": (started.elapsed().as_secs_f64() * 1000.0)
            }));
            (200, "application/json".into(), json!({"result": text}).to_string().into_bytes())
        }

        (_, "/stats") => {
            let store = match Store::open(&state.db) {
                Ok(s) => s,
                Err(_) => return (200, "application/json".into(),
                                  json!({"stats": "(store unavailable)", "harness": []}).to_string().into_bytes()),
            };
            let icons = state.icons_dir();
            let list = loci_core::harness::load_with_icons(&state.cfg, &icons);
            let rows = loci_core::harness::stats(&state.cfg, &store, &list);
            (200, "application/json".into(),
             json!({"stats": stats_text(state), "harness": rows}).to_string().into_bytes())
        }

        ("POST", "/harness") => (200, "application/json".into(), json!({
            "result": "(harness digests need an LLM call that this build does not make yet — \
                       run the Python build for summaries; detection and stats are live here)"
        }).to_string().into_bytes()),
        (_, "/graph") => {
            let store = match Store::open(&state.db) {
                Ok(s) => s,
                Err(_) => return (200, "application/json".into(),
                                  json!({"nodes": [], "links": []}).to_string().into_bytes()),
            };
            let per: std::collections::HashMap<String, usize> =
                store_per_source(state).into_iter().collect();
            let link_map = store.link_map().unwrap_or_default();

            // Nodes are files that exist in the index. A link to a note that was
            // never indexed stays a bare target inside `links` — the client
            // resolves targets by name and reports the rest as unresolved, so
            // adding a node here would double-count every real note.
            let mut nodes: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
            let mut links: Vec<[String; 2]> = Vec::new();
            for src in per.keys() {
                nodes.insert(src.clone());
            }
            for (src, targets) in &link_map {
                if per.contains_key(src) {
                    nodes.insert(src.clone());
                }
                for t in targets {
                    links.push([src.clone(), t.clone()]);
                }
            }
            let nodes: Vec<Value> = nodes
                .into_iter()
                .map(|p| json!({"path": p, "chunks": per.get(&p).cloned().unwrap_or(0)}))
                .collect();
            (200, "application/json".into(),
             json!({"nodes": nodes, "links": links}).to_string().into_bytes())
        }
        (_, "/harness") => {
            let store = match Store::open(&state.db) {
                Ok(s) => s,
                Err(_) => return (200, "application/json".into(),
                                  json!({"harness": []}).to_string().into_bytes()),
            };
            let icons = state.icons_dir();
            let list = loci_core::harness::load_with_icons(&state.cfg, &icons);
            let rows = loci_core::harness::stats(&state.cfg, &store, &list);
            (200, "application/json".into(),
             json!({"harness": rows}).to_string().into_bytes())
        }
        (_, "/harness-files") => (404, "application/json".into(), json!({"error": "harness files are not available in the native build"}).to_string().into_bytes()),

        (_, "/sources") => {
            let per = store_per_source(state);
            // show the actual corpus root so the demo's location is not a mystery
            println!("loci: sources requested (root: {})", state.root.display());
            let sources: Vec<Value> = state.cfg.sources.iter().map(|s| {
                let path = s.path.clone();
                let chunks: usize = per
                    .iter()
                    .filter(|(src, _)| src.starts_with(&path))
                    .map(|(_, n)| *n)
                    .sum();
                json!({"path": path, "chunks": chunks})
            }).collect();
            (200, "application/json".into(), json!({
                "sources": sources,
                "uploads_dir": state.uploads.display().to_string(),
                "accepted": [".md", ".markdown", ".txt", ".org", ".html", ".htm"],
                "max_bytes": UPLOAD_MAX_BYTES,
                "indexed": {"chunks": per.iter().map(|(_, n)| n).sum::<usize>(),
                            "files": per.len()}
            }).to_string().into_bytes())
        }

        ("POST", "/upload") => upload(state, body),
        ("POST", "/ingest") => {
            let mut store = match Store::open(&state.db) {
                Ok(s) => s,
                Err(e) => return (500, "application/json".into(), json!({"error": format!("{e:#}")}).to_string().into_bytes()),
            };
            let embedder = state.embedder();
            let r = ingest(&state.cfg, &mut store, embedder.as_ref(), body.get("force").and_then(|v| v.as_bool()).unwrap_or(false));
            match r {
                Ok(rep) => {
                    state.log_audit("ingest", &format!("{} added / {} updated", rep.added, rep.updated));
                    (200, "application/json".into(), json!({
                        "result": format!("Done: {} added / {} updated / {} skipped — {} chunks in store",
                                          rep.added, rep.updated, rep.skipped,
                                          Store::open(&state.db).map(|s| s.count().unwrap_or(0)).unwrap_or(0))
                    }).to_string().into_bytes())
                }
                Err(e) => (500, "application/json".into(), json!({"error": format!("{e:#}")}).to_string().into_bytes()),
            }
        }

        (_, "/queries") => {
            let limit: usize = qget(&q, "limit").and_then(|v| v.parse().ok()).unwrap_or(100).clamp(1, RING);
            let q = state.queries.lock().expect("queries");
            let rows: Vec<Value> = q.iter().take(limit).cloned().collect();
            (200, "application/json".into(), json!({"queries": rows}).to_string().into_bytes())
        }
        (_, "/audit") => {
            let a = state.audit.lock().expect("audit");
            let rows: Vec<Value> = a.iter().take(100).cloned().collect();
            (200, "application/json".into(), json!({"audit": rows}).to_string().into_bytes())
        }

        (_, "/memories") => (200, "application/json".into(),
                             json!({"memories": list_memories(state)}).to_string().into_bytes()),
        (_, "/memory") if method == "GET" => {
            let name = qget(&q, "name").unwrap_or("");
            match safe_memory(state, name) {
                Some(p) => match std::fs::read_to_string(&p) {
                    Ok(text) => (200, "application/json".into(),
                                 json!({"name": name, "text": text}).to_string().into_bytes()),
                    Err(e) => (500, "application/json".into(), json!({"error": e.to_string()}).to_string().into_bytes()),
                },
                None => (404, "application/json".into(), json!({"error": "not found"}).to_string().into_bytes()),
            }
        }
        ("POST", "/memory") => memory_write(state, body),
        ("POST", "/remember") => remember_write(state, body),
        ("DELETE", "/memory") => memory_delete(state, qget(&q, "name").unwrap_or("")),

        (_, "/source-file") => (404, "application/json".into(),
                                json!({"error": "not available in the native build"}).to_string().into_bytes()),

        _ => (404, "application/json".into(), json!({"error": "not found"}).to_string().into_bytes()),
    }
}

fn store_per_source(state: &ConsoleState) -> Vec<(String, usize)> {
    Store::open(&state.db)
        .and_then(|s| s.per_source())
        .map(|m| m.into_iter().collect())
        .unwrap_or_default()
}

fn stats_text(state: &ConsoleState) -> String {
    let per = store_per_source(state);
    let mut lines = vec![
        format!("store      : {}  ({} chunks)", state.db.display(),
                Store::open(&state.db).map(|s| s.count().unwrap_or(0)).unwrap_or(0)),
        format!("models     : {} (embed) / {} (llm)", state.cfg.embed.model, state.cfg.llm.model),
        format!("retrieval  : hybrid {} (rrf_k={}), top_k={}, tokenizer={}",
                state.cfg.retrieval.hybrid, state.cfg.retrieval.rrf_k,
                state.cfg.retrieval.top_k, state.cfg.bm25.tokenizer),
        "sources    :".into(),
    ];
    let mut rows: Vec<_> = per.into_iter().collect();
    rows.sort_by(|a, b| a.0.cmp(&b.0));
    if rows.is_empty() {
        lines.push("  (index is empty — run `loci ingest` first)".into());
    }
    for (path, n) in rows {
        lines.push(format!("  {path}  {n} chunks"));
    }
    lines.join("\n")
}

fn citation(h: &loci_core::retriever::Hit) -> String {
    if h.section.is_empty() {
        h.source.clone()
    } else {
        format!("{} > {}", h.source, h.section)
    }
}

// ---- memory notes ----------------------------------------------------------

fn safe_memory(state: &ConsoleState, name: &str) -> Option<PathBuf> {
    let base = name.replace('\\', "/").rsplit('/').next()?.to_string();
    if base.is_empty() || !base.ends_with(".md") || base.starts_with('.') {
        return None;
    }
    let p = state.memories.join(&base);
    let canonic = p.canonicalize().ok()?;
    canonic.starts_with(state.memories.canonicalize().ok()?).then_some(canonic)
}

fn list_memories(state: &ConsoleState) -> Vec<Value> {
    let mut rows = Vec::new();
    let mut paths: Vec<PathBuf> = std::fs::read_dir(&state.memories)
        .map(|rd| rd.flatten().map(|e| e.path()).collect())
        .unwrap_or_default();
    paths.sort();
    for p in paths {
        if p.extension().and_then(|e| e.to_str()) != Some("md") {
            continue;
        }
        if let Some(rel) = p.strip_prefix(&state.memories).ok().map(|r| r.to_path_buf()) {
            if rel.starts_with(".trash") {
                continue;
            }
            let head = std::fs::read_to_string(&p).unwrap_or_default().chars().take(400).collect::<String>();
            let title = if head.starts_with("---") {
                head.lines()
                    .find(|l| l.starts_with("title:"))
                    .map(|l| l.trim_start_matches("title:").trim().trim_matches('"').to_string())
                    .unwrap_or_default()
            } else {
                String::new()
            };
            rows.push(json!({
                "name": rel.to_string_lossy(),
                "group": "shared",
                "harness": "",
                "size": std::fs::metadata(&p).map(|m| m.len()).unwrap_or(0),
                "mtime": file_mtime_str(&p),
                "title": if title.is_empty() { p.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default() } else { title }
            }));
        }
    }
    rows
}

fn file_mtime_str(p: &Path) -> String {
    std::fs::metadata(p)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| {
            let secs = d.as_secs();
            format!("{:04}-{:02}-{:02} {:02}:{:02}",
                    1970 + secs / 31_536_000, (secs / 2_592_000) % 12 + 1,
                    (secs / 86_400) % 30 + 1, (secs / 3600) % 24, (secs / 60) % 60)
        })
        .unwrap_or_else(|| "—".into())
}

fn slugify(text: &str) -> String {
    let cleaned: String = text
        .to_lowercase()
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect();
    cleaned.split('-').filter(|s| !s.is_empty()).collect::<Vec<_>>().join("-")
}

fn index_one(state: &ConsoleState, path: &Path) -> Result<usize> {
    let doc = load_one(path)
        .context("load document")?
        .ok_or_else(|| anyhow::anyhow!("unsupported or empty file: {}", path.display()))?;
    let chunks = chunker::split_markdown(
        &doc.body,
        ChunkParams { size: state.cfg.chunk.size, overlap: state.cfg.chunk.overlap },
    );
    if chunks.is_empty() {
        anyhow::bail!("no indexable text");
    }
    let embedder = state.embedder();
    let store = Store::open(&state.db)?;
    let texts: Vec<String> = chunks.iter().map(|c| c.text.clone()).collect();
    let chashes: Vec<String> = texts.iter().map(|t| loader::chunk_hash(t)).collect();
    let reuse = store.reuse_map(&doc.path.to_string_lossy())?;
    let mut vectors: Vec<Option<Vec<f32>>> = chashes
        .iter()
        .map(|h| reuse.get(h).cloned())
        .collect();
    let missing: Vec<usize> = vectors
        .iter()
        .enumerate()
        .filter(|(_, v)| v.is_none())
        .map(|(i, _)| i)
        .collect();
    if !missing.is_empty() {
        let to_embed: Vec<String> = missing.iter().map(|i| texts[*i].clone()).collect();
        let fresh = embedder.embed(&to_embed)?;
        for (slot, v) in missing.iter().zip(fresh) {
            vectors[*slot] = Some(v);
        }
    }
    let final_vectors: Vec<Vec<f32>> = vectors.into_iter().map(|v| v.unwrap_or_default()).collect();
    let pairs: Vec<(String, String)> = chunks
        .iter()
        .map(|c| (c.text.clone(), c.section.clone()))
        .collect();
    let links = doc.links.clone();
    store.upsert_source(&loci_core::store::SourceWrite {
        source: &doc.path.to_string_lossy(),
        file_hash: &doc.hash,
        mtime: doc.mtime,
        tags: &doc.tags,
        chunks: &pairs,
        chashes: &chashes,
        vectors: &final_vectors,
        links: &links,
    })
}

/// `POST /remember` — the Python build's memory-capture endpoint, mirrored so
/// clients written against it (loci-dsh's quick capture) work unchanged against
/// the native build. Same filename scheme (`YYYYMMDD-HHMMSS-slug.md` — the
/// filename IS the timestamp loci-dsh's timeline parses), same frontmatter,
/// same response text.
fn remember_write(state: &ConsoleState, body: Value) -> (u16, String, Vec<u8>) {
    let text = body.get("text").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
    if text.is_empty() {
        return (400, "application/json".into(),
                json!({"error": "text is required"}).to_string().into_bytes());
    }
    let tags: Vec<String> = body
        .get("tags")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|t| t.as_str()).map(str::to_string).collect())
        .unwrap_or_default();
    let title = body
        .get("title")
        .and_then(|v| v.as_str())
        .map(|t| t.trim().to_string())
        .filter(|t| !t.is_empty())
        .unwrap_or_else(|| {
            text.lines().find(|l| !l.trim().is_empty()).unwrap_or("memory").trim().to_string()
        });
    let title: String = title.chars().take(80).collect();

    std::fs::create_dir_all(&state.memories).ok();
    let (y, mo, d, h, mi, sec) = now_datetime();
    let base = format!("{y:04}{mo:02}{d:02}-{h:02}{mi:02}{sec:02}-{}", slugify(&title));
    let mut path = state.memories.join(format!("{base}.md"));
    let mut n = 2;
    while path.exists() {                       // two IDEs writing in the same second
        path = state.memories.join(format!("{base}-{n}.md"));
        n += 1;
    }
    let mut tag_list = vec!["memory".to_string()];
    tag_list.extend(tags.iter().filter(|t| !t.trim().is_empty()).cloned());
    let iso = format!("{y:04}-{mo:02}-{d:02} {h:02}:{mi:02}");
    let front = format!("---\ntags: [{}]\ncreated: {iso}\ntitle: {title}\n---\n",
                        tag_list.join(", "));
    let tmp = path.with_extension("md.tmp");
    if std::fs::write(&tmp, format!("{front}# {title}\n\n{text}\n")).is_err() {
        return (500, "application/json".into(),
                json!({"error": "cannot write memory file"}).to_string().into_bytes());
    }
    std::fs::rename(&tmp, &path).ok();          // atomic, overwrites on Windows

    match index_one(state, &path) {
        Ok(chunks) => {
            state.log_audit("remember",
                &path.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default());
            (200, "application/json".into(),
             json!({"result": format!("remembered: {} ({chunks} chunks, searchable now)",
                                      path.display())}).to_string().into_bytes())
        }
        Err(e) => (500, "application/json".into(),
                   json!({"error": format!("{e:#}")}).to_string().into_bytes()),
    }
}

/// Civil date and time-of-day from the system clock, no chrono dependency.
fn now_datetime() -> (i64, u32, u32, u32, u32, u32) {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs() as i64;
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    // Howard Hinnant's civil-from-days
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    let y = if m <= 2 { y + 1 } else { y };
    (y, m, d, (rem / 3600) as u32, (rem % 3600 / 60) as u32, (rem % 60) as u32)
}

fn memory_write(state: &ConsoleState, body: Value) -> (u16, String, Vec<u8>) {
    let text = body.get("text").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
    if text.is_empty() {
        return (400, "application/json".into(), json!({"error": "text is required"}).to_string().into_bytes());
    }
    std::fs::create_dir_all(&state.memories).ok();

    let path = match body.get("name").and_then(|v| v.as_str()) {
        Some(name) => match safe_memory(state, name) {
            Some(p) => p,                                   // update: keep frontmatter
            None => return (404, "application/json".into(), json!({"error": "not found"}).to_string().into_bytes()),
        },
        None => {
            let title = body.get("title").and_then(|v| v.as_str())
                .map(|t| t.chars().take(80).collect::<String>())
                .unwrap_or_else(|| text.lines().next().unwrap_or("memory").to_string());
            let ts = std::time::SystemTime::now()
                .duration_since(UNIX_EPOCH).unwrap_or_default().as_secs();
            let mut path = state.memories.join(format!("{ts}-{}.md", slugify(&title)));
            let mut n = 2;
            while path.exists() {
                path = state.memories.join(format!("{ts}-{}-{n}.md", slugify(&title)));
                n += 1;
            }
            let iso = now_str();
            let front = format!("---\ntags: [memory]\ncreated: {iso}\ntitle: {title}\n---\n");
            std::fs::write(&path, format!("{front}# {title}\n\n{text}\n")).ok();
            path
        }
    };

    match index_one(state, &path) {
        Ok(chunks) => {
            state.log_audit("memory.write", &path.file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default());
            (200, "application/json".into(), json!({
                "path": path.display().to_string(), "chunks": chunks
            }).to_string().into_bytes())
        }
        Err(e) => (500, "application/json".into(), json!({"error": format!("{e:#}")}).to_string().into_bytes()),
    }
}

fn memory_delete(state: &ConsoleState, name: &str) -> (u16, String, Vec<u8>) {
    let Some(p) = safe_memory(state, name) else {
        return (404, "application/json".into(), json!({"error": "not found"}).to_string().into_bytes());
    };
    let trash = state.memories.join(".trash");
    std::fs::create_dir_all(&trash).ok();
    let mut dest = trash.join(p.file_name().unwrap_or_default());
    let mut n = 2;
    while dest.exists() {
        dest = trash.join(format!("{}-{n}.md", p.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default()));
        n += 1;
    }
    std::fs::rename(&p, &dest).ok();
    if let Ok(store) = Store::open(&state.db) {
        let _ = store.delete_source(&p.to_string_lossy());
    }
    state.log_audit("memory.delete", name);
    (200, "application/json".into(), json!({"trashed": dest.display().to_string()}).to_string().into_bytes())
}

// ---- upload ----------------------------------------------------------------

fn upload(state: &ConsoleState, body: Value) -> (u16, String, Vec<u8>) {
    let raw_name = body.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let base = raw_name.replace('\\', "/").rsplit('/').next().unwrap_or("").trim().to_string();
    if base.is_empty() || base.starts_with('.') {
        return (400, "application/json".into(), json!({"error": "name is required"}).to_string().into_bytes());
    }
    let name: String = base.chars().take(120).collect();
    let suffix = Path::new(&name)
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| format!(".{}", e.to_lowercase()))
        .unwrap_or_default();
    let accepted = [".md", ".markdown", ".txt", ".org", ".html", ".htm"];
    if !accepted.contains(&suffix.as_str()) {
        return (400, "application/json".into(), json!({
            "error": format!("unsupported type {suffix}"), "accepted": accepted
        }).to_string().into_bytes());
    }

    let raw = body.get("data").and_then(|v| v.as_str()).unwrap_or("");
    let blob = match base64::engine::general_purpose::STANDARD.decode(raw.split(',').nth(1).unwrap_or(raw)) {
        Ok(b) => b,
        Err(_) => return (400, "application/json".into(), json!({"error": "data must be base64"}).to_string().into_bytes()),
    };
    if blob.is_empty() {
        return (400, "application/json".into(), json!({"error": "empty file"}).to_string().into_bytes());
    }

    std::fs::create_dir_all(&state.uploads).ok();
    let mut dest = state.uploads.join(&name);
    let mut n = 2;
    while dest.exists() {
        dest = state.uploads.join(format!("{}-{n}{}",
            Path::new(&name).file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_default(),
            suffix));
        n += 1;
    }
    if std::fs::write(&dest, &blob).is_err() {
        return (500, "application/json".into(), json!({"error": "cannot write file"}).to_string().into_bytes());
    }

    match index_one(state, &dest) {
        Ok(chunks) => {
            state.log_audit("upload", &format!("{name} ({chunks} chunks)"));
            (200, "application/json".into(), json!({
                "file": dest.file_name().map(|s| s.to_string_lossy().to_string().into_bytes()).unwrap_or_default(),
                "path": dest.display().to_string(), "chunks": chunks, "bytes": blob.len()
            }).to_string().into_bytes())
        }
        Err(e) => {
            std::fs::remove_file(&dest).ok();   // no orphan pretending to be indexed
            (400, "application/json".into(), json!({"error": format!("{e:#}")}).to_string().into_bytes())
        }
    }
}

// ---- ask (LLM) ---------------------------------------------------------------

fn llm_answer(cfg: &Config, question: &str, hits: &[loci_core::retriever::Hit]) -> String {
    if hits.is_empty() {
        return "(nothing relevant in the knowledge base)".into();
    }
    if cfg.llm.api_key.is_empty() || cfg.llm.model.is_empty() {
        return "(ask needs an LLM — set [llm] api_key and model in config.toml; search still works)".into();
    }
    let context: String = hits
        .iter()
        .enumerate()
        .map(|(i, h)| {
            let sec = if h.section.is_empty() { String::new() } else { format!(" | section: {}", h.section) };
            format!("[chunk {} | source: {}{}]\n{}", i + 1, h.source, sec, h.text)
        })
        .collect::<Vec<_>>()
        .join("\n\n---\n\n");

    let client = match reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()
    {
        Ok(c) => c,
        Err(e) => return format!("(ask failed: {e})"),
    };
    let body = json!({
        "model": cfg.llm.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content":
                format!("Excerpts:\n\n{context}\n\n---\n\nQuestion: {question}")}
        ],
        "temperature": 0.3
    });
    let resp = client
        .post(format!("{}/chat/completions", cfg.llm.base_url.trim_end_matches('/')))
        .bearer_auth(&cfg.llm.api_key)
        .json(&body)
        .send();
    match resp {
        Ok(r) => match r.error_for_status() {
            Ok(r) => {
                let v: Value = r.json().unwrap_or(Value::Null);
                v.pointer("/choices/0/message/content")
                    .and_then(|c| c.as_str())
                    .unwrap_or("(the model returned no content)")
                    .to_string()
            }
            Err(e) => format!("(ask failed: {e})"),
        },
        Err(e) => format!("(ask failed: {e})"),
    }
}

// ---- demo corpus ------------------------------------------------------------

const DEMO_NOTES: &[(&str, &str)] = &[
    ("projects/aurora/decisions.md", "# Aurora — decisions\n\n## ADR-001: SHT45 over BME280\n\nRevision A used a BME280. The balcony sits between 80% and 100% relative humidity for most of the winter, and the BME280 drifted upward by roughly 6% RH after two months. Decision: SHT45.\n"),
    ("projects/aurora/battery-budget.md", "# Aurora — power budget\n\nTarget: six months on one charge, sampling every five minutes. The MCU wake window dominates at 7.68 mAh/day; total draw is 9.52 mAh/day.\n"),
    ("projects/aurora/retro.md", "# Retro 2026-09-18\n\n## What did not\n\nWi-Fi reconnect storms cost 120 mAh over two days. The antenna drops to -78 dBm when the balcony door is closed.\n"),
    ("notes/reading-list.md", "# Reading list\n\n## Electronics\n\nThe Art of Electronics, chapter 9 on voltage references.\n"),
];
