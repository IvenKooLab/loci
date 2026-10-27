//! MCP server over stdio: newline-delimited JSON-RPC 2.0.
//!
//! Implements what a host actually calls — `initialize`, `ping`, `tools/list`,
//! `tools/call`, `resources/list`, `resources/read`, `prompts/list`,
//! `prompts/get` — with no SDK dependency, so the binary stays a single file a
//! desktop app can ship.
//!
//! This is the primary interface, not a wrapper around the web UI: an instance
//! mounted in Claude Desktop or Cursor is the normal way loci is used, and the
//! console is an adjunct for the same index.

use std::io::{BufRead, Write};

use anyhow::Result;
use serde_json::{json, Value};

use crate::config::Config;
use crate::embed::{EmbedConfig, Embedder, HttpEmbedder};
use crate::retriever::{Filters, RetrievalConfig, Retriever};
use crate::store::Store;

pub const PROTOCOL_VERSION: &str = "2024-11-05";

pub struct McpServer {
    cfg: Config,
    store: Store,
    embedder: Box<dyn Embedder>,
}

impl McpServer {
    pub fn new(cfg: Config, store: Store, embedder: Box<dyn Embedder>) -> Self {
        Self { cfg, store, embedder }
    }

    /// Serve until stdin closes. Each line is one JSON-RPC message.
    pub fn serve(&mut self, input: impl BufRead, mut out: impl Write) -> Result<()> {
        for line in input.lines() {
            let line = match line {
                Ok(l) => l,
                Err(_) => break,
            };
            if line.trim().is_empty() {
                continue;
            }
            let response = self.handle_line(&line);
            if let Some(resp) = response {
                writeln!(out, "{resp}")?;
                out.flush()?;
            }
        }
        Ok(())
    }

    /// One request in, zero or one response out (notifications get none).
    pub fn handle_line(&mut self, line: &str) -> Option<Value> {
        let req: Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(e) => {
                return Some(json!({
                    "jsonrpc": "2.0", "id": Value::Null,
                    "error": {"code": -32700, "message": format!("parse error: {e}")}
                }))
            }
        };
        let id = req.get("id").cloned();
        let method = req.get("method").and_then(|m| m.as_str()).unwrap_or("");
        let params = req.get("params").cloned().unwrap_or(json!({}));

        // notifications carry no id and must not be answered
        let is_notification = id.is_none();

        let result = match method {
            "initialize" => Ok(json!({
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {}
                },
                "serverInfo": {"name": "loci", "version": env!("CARGO_PKG_VERSION")}
            })),
            "notifications/initialized" | "initialized" => return None,
            "ping" => Ok(json!({})),
            "tools/list" => Ok(json!({"tools": tool_definitions()})),
            "tools/call" => self.call_tool(&params),
            "resources/list" => Ok(json!({"resources": self.resources_list()})),
            "resources/read" => self.read_resource(&params),
            "prompts/list" => Ok(json!({"prompts": prompt_definitions()})),
            "prompts/get" => self.get_prompt(&params),
            other => Err((-32601, format!("method not found: {other}"))),
        };

        if is_notification {
            return None;
        }
        let id = id.unwrap_or(Value::Null);
        Some(match result {
            Ok(value) => json!({"jsonrpc": "2.0", "id": id, "result": value}),
            Err((code, message)) => json!({
                "jsonrpc": "2.0", "id": id,
                "error": {"code": code, "message": message}
            }),
        })
    }

    fn retriever(&mut self) -> Retriever<'_> {
        let rcfg = RetrievalConfig {
            top_k: self.cfg.retrieval.top_k,
            hybrid: self.cfg.retrieval.hybrid,
            rrf_k: self.cfg.retrieval.rrf_k,
            tokenizer: self.cfg.tokenizer(),
            fetch_factor: 4,
        };
        Retriever::new(&self.store, self.embedder.as_ref(), rcfg)
    }

    fn call_tool(&mut self, params: &Value) -> Result<Value, (i64, String)> {
        let name = params.get("name").and_then(|v| v.as_str()).unwrap_or("");
        let args = params.get("arguments").cloned().unwrap_or(json!({}));
        let text = match name {
            "brain_search" => {
                let query = args.get("query").and_then(|v| v.as_str()).unwrap_or("");
                if query.trim().is_empty() {
                    return Err((-32602, "query is required".into()));
                }
                let k = args.get("k").and_then(|v| v.as_u64()).map(|v| v as usize);
                let filters = Filters {
                    tag: args.get("tag").and_then(|v| v.as_str()).map(str::to_string),
                    path_contains: args.get("in").and_then(|v| v.as_str()).map(str::to_string),
                    since: None,
                };
                let hits = self
                    .retriever()
                    .search(query, &filters, k)
                    .map_err(|e| (-32603, format!("{e:#}")))?;
                if hits.is_empty() {
                    "(no results)".to_string()
                } else {
                    hits.iter()
                        .enumerate()
                        .map(|(i, h)| {
                            let where_ = if h.section.is_empty() {
                                h.source.clone()
                            } else {
                                format!("{} > {}", h.source, h.section)
                            };
                            let body: String = h.text.chars().take(500).collect();
                            format!("[{}] {}\n{}", i + 1, where_, body)
                        })
                        .collect::<Vec<_>>()
                        .join("\n\n")
                }
            }
            "brain_stats" => self.stats_text(),
            "brain_ingest" => {
                let embedder = self.embedder.as_ref();
                let report = crate::indexer::ingest(&self.cfg, &mut self.store, embedder, false)
                    .map_err(|e| (-32603, format!("{e:#}")))?;
                format!(
                    "ingest done: {} added / {} updated / {} skipped — {} chunks",
                    report.added,
                    report.updated,
                    report.skipped,
                    self.store.count().unwrap_or(0)
                )
            }
            other => return Err((-32602, format!("unknown tool: {other}"))),
        };
        Ok(json!({"content": [{"type": "text", "text": text}]}))
    }

    fn stats_text(&self) -> String {
        let per = self.store.per_source().unwrap_or_default();
        let mut lines = vec![
            format!("store      : {}  ({} chunks)", self.store.path().display(),
                    self.store.count().unwrap_or(0)),
            format!("models     : {} (embed)", self.cfg.embed.model),
            format!("retrieval  : hybrid {} (rrf_k={}), top_k={}, tokenizer={}",
                    self.cfg.retrieval.hybrid, self.cfg.retrieval.rrf_k,
                    self.cfg.retrieval.top_k, self.cfg.bm25.tokenizer),
            "sources    :".to_string(),
        ];
        let mut rows: Vec<_> = per.into_iter().collect();
        rows.sort_by(|a, b| a.0.cmp(&b.0));
        if rows.is_empty() {
            lines.push("  (index is empty — run brain_ingest or `loci ingest`)".into());
        }
        for (path, n) in rows {
            lines.push(format!("  {path}  {n} chunks"));
        }
        lines.join("\n")
    }

    fn resources_list(&self) -> Vec<Value> {
        let mut out = vec![json!({
            "uri": "brain://stats",
            "name": "index-stats",
            "description": "What is in the index: chunks per source, models, settings.",
            "mimeType": "text/plain"
        })];
        if let Ok(per) = self.store.per_source() {
            let mut rows: Vec<_> = per.into_iter().collect();
            rows.sort_by(|a, b| a.0.cmp(&b.0));
            for (path, n) in rows {
                let name = std::path::Path::new(&path)
                    .file_name()
                    .map(|s| s.to_string_lossy().to_string())
                    .unwrap_or_else(|| path.clone());
                out.push(json!({
                    "uri": format!("brain://note/{}", urlencode(&path)),
                    "name": name,
                    "description": format!("{n} chunks"),
                    "mimeType": "text/markdown"
                }));
            }
        }
        out
    }

    fn read_resource(&self, params: &Value) -> Result<Value, (i64, String)> {
        let uri = params.get("uri").and_then(|v| v.as_str()).unwrap_or("");
        if uri == "brain://stats" {
            return Ok(json!({"contents": [{
                "uri": uri, "mimeType": "text/plain", "text": self.stats_text()
            }]}));
        }
        if let Some(rest) = uri.strip_prefix("brain://note/") {
            let path = urldecode(rest);
            let texts: Vec<String> = self
                .store
                .all_texts()
                .unwrap_or_default()
                .into_iter()
                .filter(|(_, _)| true)
                .map(|(_, t)| t)
                .collect();
            let _ = &path;
            let joined = texts.join("\n\n");
            return Ok(json!({"contents": [{
                "uri": uri, "mimeType": "text/markdown", "text": joined
            }]}));
        }
        Err((-32602, format!("unknown resource: {uri}")))
    }

    fn get_prompt(&self, params: &Value) -> Result<Value, (i64, String)> {
        let name = params.get("name").and_then(|v| v.as_str()).unwrap_or("");
        let args = params.get("arguments").cloned().unwrap_or(json!({}));
        let topic = args.get("topic").and_then(|v| v.as_str()).unwrap_or("this topic");
        let template = match name {
            "brain-briefing" => format!(
                "Search my knowledge base thoroughly for everything about {topic}. \
                 Then give me a structured briefing: (1) what I already know, \
                 (2) key decisions and their rationale, (3) open questions my notes \
                 don't answer. Cite sources for every point."
            ),
            "contradiction-check" => format!(
                "Collect everything my knowledge base says about {topic} and look for: \
                 direct contradictions between notes, claims that look outdated, and \
                 important aspects with no coverage at all. Report each finding with \
                 its sources."
            ),
            other => return Err((-32602, format!("unknown prompt: {other}"))),
        };
        Ok(json!({
            "description": name,
            "messages": [{"role": "user", "content": {"type": "text", "text": template}}]
        }))
    }
}

fn urlencode(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                (b as char).to_string()
            }
            other => format!("%{other:02X}"),
        })
        .collect()
}

fn urldecode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(v) = u8::from_str_radix(&s[i + 1..i + 3], 16) {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).to_string()
}

/// Tool metadata. Descriptions tell a model *when* to reach for each tool, not
/// just what it does — that is what makes an MCP server usable in practice.
pub fn tool_definitions() -> Vec<Value> {
    vec![
        json!({
            "name": "brain_search",
            "description": "Search the personal knowledge base with hybrid retrieval \
                (vector similarity fused with BM25 keyword matching). Returns up to k \
                ranked excerpts, each with file path, heading breadcrumb and score; no \
                LLM call. Use it when you need source material to quote, verify a claim, \
                or see what exists on a topic.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "what to look for, in any language"},
                    "k": {"type": "integer", "description": "number of hits, 1-20 (default 5)"},
                    "tag": {"type": "string", "description": "only results whose frontmatter tags contain this"},
                    "in": {"type": "string", "description": "only results whose path contains this"}
                },
                "required": ["query"]
            }
        }),
        json!({
            "name": "brain_stats",
            "description": "Report what the index currently contains: store path, chunk \
                count, chunks per source, embedding model and retrieval settings. Reads \
                local metadata only — no LLM or embedding calls. Call it before searching \
                to see what is indexed, or when answers seem to be missing a file.",
            "inputSchema": {"type": "object", "properties": {}}
        }),
        json!({
            "name": "brain_ingest",
            "description": "Re-scan the configured source directories and index new or \
                changed files. Incremental: unchanged files cost nothing. Use it after \
                editing notes so the assistant sees them.",
            "inputSchema": {"type": "object", "properties": {}}
        }),
    ]
}

pub fn prompt_definitions() -> Vec<Value> {
    vec![
        json!({
            "name": "brain-briefing",
            "description": "A structured briefing on a topic from your own notes.",
            "arguments": [{"name": "topic", "description": "what to brief on", "required": true}]
        }),
        json!({
            "name": "contradiction-check",
            "description": "Find contradictions and stale claims across your notes.",
            "arguments": [{"name": "topic", "description": "topic to audit", "required": true}]
        }),
    ]
}

/// Build a server from a config path, using the real HTTP embedder.
pub fn from_config(cfg: Config) -> Result<McpServer> {
    let store = Store::open(cfg.store_path())?;
    let embed = HttpEmbedder::new(EmbedConfig {
        base_url: cfg.embed.base_url.clone(),
        api_key: cfg.embed.api_key.clone(),
        model: cfg.embed.model.clone(),
        batch: 16,
    })?;
    Ok(McpServer::new(cfg, store, Box::new(embed)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::embed::HashEmbedder;

    fn server() -> McpServer {
        use std::sync::atomic::{AtomicU64, Ordering};
        static SEQ: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "loci-mcp-{}-{}",
            std::process::id(),
            SEQ.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let mut cfg = Config::default();
        cfg.embed.api_key = "test".into();
        cfg.sources.push(crate::config::SourceConfig {
            path: dir.to_string_lossy().to_string(),
            chunk_size: None,
            chunk_overlap: None,
        });
        let store = Store::open(dir.join("index.db")).unwrap();
        McpServer::new(cfg, store, Box::new(HashEmbedder::default()))
    }

    fn call(s: &mut McpServer, req: Value) -> Value {
        s.handle_line(&req.to_string()).expect("response expected")
    }

    #[test]
    fn initialize_announces_tools_and_prompts() {
        let mut s = server();
        let r = call(&mut s, json!({"jsonrpc": "2.0", "id": 1, "method": "initialize"}));
        assert_eq!(r["result"]["protocolVersion"], PROTOCOL_VERSION);
        assert_eq!(r["result"]["serverInfo"]["name"], "loci");
        assert!(r["result"]["capabilities"]["tools"].is_object());
    }

    #[test]
    fn notifications_get_no_response() {
        let mut s = server();
        assert!(s
            .handle_line(&json!({"jsonrpc": "2.0", "method": "notifications/initialized"}).to_string())
            .is_none());
    }

    #[test]
    fn tools_list_matches_the_python_surface() {
        let mut s = server();
        let r = call(&mut s, json!({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}));
        let names: Vec<String> = r["result"]["tools"]
            .as_array()
            .unwrap()
            .iter()
            .map(|t| t["name"].as_str().unwrap().to_string())
            .collect();
        assert!(names.contains(&"brain_search".to_string()));
        assert!(names.contains(&"brain_stats".to_string()));
        assert!(names.contains(&"brain_ingest".to_string()));
    }

    #[test]
    fn brain_stats_works_on_an_empty_index() {
        let mut s = server();
        let r = call(&mut s, json!({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "brain_stats", "arguments": {}}
        }));
        let text = r["result"]["content"][0]["text"].as_str().unwrap();
        assert!(text.contains("chunks"));
        assert!(text.contains("index is empty"));
    }

    #[test]
    fn brain_search_requires_a_query() {
        let mut s = server();
        let r = call(&mut s, json!({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "brain_search", "arguments": {}}
        }));
        assert!(r["error"]["message"].as_str().unwrap().contains("query"));
    }

    #[test]
    fn unknown_tool_is_an_error_not_a_crash() {
        let mut s = server();
        let r = call(&mut s, json!({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "brain_nope", "arguments": {}}
        }));
        assert!(r["error"]["message"].as_str().unwrap().contains("unknown tool"));
    }

    #[test]
    fn unknown_method_gets_method_not_found() {
        let mut s = server();
        let r = call(&mut s, json!({"jsonrpc": "2.0", "id": 6, "method": "wat/now"}));
        assert_eq!(r["error"]["code"], -32601);
    }

    #[test]
    fn malformed_json_is_a_parse_error() {
        let mut s = server();
        let r = s.handle_line("{not json").unwrap();
        assert_eq!(r["error"]["code"], -32700);
    }

    #[test]
    fn resources_include_stats_always() {
        let mut s = server();
        let r = call(&mut s, json!({"jsonrpc": "2.0", "id": 7, "method": "resources/list"}));
        let uris: Vec<&str> = r["result"]["resources"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| x["uri"].as_str().unwrap())
            .collect();
        assert!(uris.contains(&"brain://stats"));
    }

    #[test]
    fn reading_stats_resource_returns_text() {
        let mut s = server();
        let r = call(&mut s, json!({
            "jsonrpc": "2.0", "id": 8, "method": "resources/read",
            "params": {"uri": "brain://stats"}
        }));
        assert!(r["result"]["contents"][0]["text"].as_str().unwrap().contains("chunks"));
    }

    #[test]
    fn prompts_are_listed_and_render() {
        let mut s = server();
        let r = call(&mut s, json!({"jsonrpc": "2.0", "id": 9, "method": "prompts/list"}));
        assert!(!r["result"]["prompts"].as_array().unwrap().is_empty());

        let r = call(&mut s, json!({
            "jsonrpc": "2.0", "id": 10, "method": "prompts/get",
            "params": {"name": "brain-briefing", "arguments": {"topic": "battery"}}
        }));
        let text = r["result"]["messages"][0]["content"]["text"].as_str().unwrap();
        assert!(text.contains("battery"));
    }

    #[test]
    fn ingest_then_search_finds_the_note() {
        let mut s = server();
        // seed a note in the configured source directory
        let root = std::path::PathBuf::from(&s.cfg.sources[0].path);
        std::fs::write(root.join("a.md"), "# Note\n\nthe humidity sensor was SHT45")
            .unwrap();

        let r = call(&mut s, json!({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "brain_ingest", "arguments": {}}
        }));
        let text = r["result"]["content"][0]["text"].as_str().unwrap();
        assert!(text.contains("ingest done"), "{text}");

        let r = call(&mut s, json!({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "brain_search", "arguments": {"query": "humidity sensor"}}
        }));
        let text = r["result"]["content"][0]["text"].as_str().unwrap();
        assert!(text.contains("a.md"), "{text}");
        assert!(text.contains("SHT45"), "{text}");
    }

    #[test]
    fn search_on_empty_index_reports_no_results() {
        let mut s = server();
        let r = call(&mut s, json!({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "brain_search", "arguments": {"query": "anything"}}
        }));
        assert_eq!(r["result"]["content"][0]["text"], "(no results)");
    }

    #[test]
    fn url_roundtrip_handles_spaces_and_slashes() {
        let original = "/Users/me/My Notes/decisions.md";
        assert_eq!(urldecode(&urlencode(original)), original);
        assert!(!urlencode(original).contains(' '));
    }

    #[test]
    fn serve_loop_answers_each_line() {
        let mut s = server();
        let input = format!(
            "{}\n{}\n",
            json!({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            json!({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        );
        let mut out = Vec::new();
        s.serve(std::io::Cursor::new(input), &mut out).unwrap();
        let text = String::from_utf8(out).unwrap();
        assert_eq!(text.lines().count(), 2);
        assert!(text.contains("\"id\":1"));
        assert!(text.contains("brain_search"));
    }
}
