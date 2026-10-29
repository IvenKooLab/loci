//! Import an index exported from the Python build (`loci export`).
//!
//! ChromaDB is only readable from Python, so migration is export-then-import
//! rather than a shared on-disk format. The export is JSONL: one chunk per
//! line, plus a `__meta__` line at the end carrying the chunk count and the
//! embedding fingerprint.
//!
//! The fingerprint matters more than the data: vectors produced by a different
//! embedding model are the same length as often as not, so importing them
//! silently poisons retrieval with distances that mean nothing. The import
//! therefore refuses when the model recorded in the export differs from the
//! one configured, unless told to force.

use std::io::{BufRead, BufReader, Write};
use std::path::Path;

use anyhow::{Context, Result};
use serde_json::Value;

use crate::store::{SourceWrite, Store};

#[derive(Debug, Default)]
pub struct ImportReport {
    pub chunks: usize,
    pub files: usize,
    pub skipped: usize,
    pub embed_model: Option<String>,
    pub embed_dim: Option<usize>,
}

/// One file's chunks, as collected while streaming the export.
struct Pending {
    tags: String,
    file_hash: String,
    mtime: f64,
    chunks: Vec<(String, String)>,
    chashes: Vec<String>,
    vectors: Vec<Vec<f32>>,
    links: Vec<String>,
}

pub fn import(
    store: &Store,
    path: &Path,
    expected_model: Option<&str>,
    force: bool,
) -> Result<ImportReport> {
    let file = std::fs::File::open(path)
        .with_context(|| format!("open {}", path.display()))?;
    let mut report = ImportReport::default();

    // group by source: the store writes one file at a time
    let mut order: Vec<String> = Vec::new();
    let mut by_source: std::collections::HashMap<String, Pending> =
        std::collections::HashMap::new();

    for line in BufReader::new(file).lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let row: Value = serde_json::from_str(&line)
            .with_context(|| "export line is not valid JSON")?;
        if let Some(meta) = row.get("__meta__") {
            report.embed_model = meta
                .get("embed_model")
                .and_then(|v| v.as_str())
                .map(str::to_string);
            report.embed_dim = meta
                .get("embed_dim")
                .and_then(|v| v.as_u64())
                .map(|v| v as usize);
            continue;
        }

        // a row without a source or vector cannot be placed: count it and move on
        let source = match row.get("source").and_then(|v| v.as_str()) {
            Some(s) if !s.is_empty() => s.to_string(),
            _ => {
                report.skipped += 1;
                continue;
            }
        };
        let vector: Vec<f32> = match row.get("vec").and_then(|v| v.as_array()) {
            Some(items) => items
                .iter()
                .filter_map(|x| x.as_f64().map(|f| f as f32))
                .collect(),
            None => {
                report.skipped += 1;
                continue;
            }
        };
        if vector.is_empty() {
            report.skipped += 1;
            continue;
        }
        if report.embed_dim.map(|d| d != vector.len()).unwrap_or(false) {
            anyhow::bail!(
                "export declares dim {} but a chunk carries {} — file is inconsistent",
                report.embed_dim.unwrap_or(0),
                vector.len()
            );
        }

        let entry = by_source.entry(source.clone()).or_insert_with(|| {
            order.push(source.clone());
            Pending {
                tags: String::new(),
                file_hash: String::new(),
                mtime: 0.0,
                chunks: Vec::new(),
                chashes: Vec::new(),
                vectors: Vec::new(),
                links: Vec::new(),
            }
        });
        entry.tags = row
            .get("tags")
            .and_then(|v| v.as_str())
            .unwrap_or(&entry.tags)
            .to_string();
        entry.file_hash = row
            .get("hash")
            .and_then(|v| v.as_str())
            .unwrap_or(&entry.file_hash)
            .to_string();
        entry.mtime = row.get("mtime").and_then(|v| v.as_f64()).unwrap_or(entry.mtime);
        entry.chunks.push((
            row.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string(),
            row.get("section").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        ));
        entry.chashes.push(
            row.get("chash").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        );
        if let Some(arr) = row.get("links").and_then(|v| v.as_array()) {
            for t in arr.iter().filter_map(|v| v.as_str()) {
                if !t.is_empty() {
                    entry.links.push(t.to_string());
                }
            }
        }
        entry.vectors.push(vector);
        report.chunks += 1;
    }

    // the embedding space must match, or the vectors are noise
    if !force {
        if let (Some(exported), Some(want)) = (report.embed_model.as_deref(), expected_model) {
            if !want.is_empty() && exported != want {
                anyhow::bail!(concat!(
                    "export was built with embedding model {exported:?}, config says {want:?}.\n",
                    "Re-export from the Python build with the same [embed] model, ",
                    "or pass --force to import anyway (retrieval quality will be wrong)."
                ), exported = exported, want = want);
            }
        }
    }

    for source in order {
        if let Some(p) = by_source.remove(&source) {
            store.upsert_source(&SourceWrite {
                source: &source,
                file_hash: &p.file_hash,
                mtime: p.mtime,
                tags: &p.tags,
                chunks: &p.chunks,
                chashes: &p.chashes,
                vectors: &p.vectors,
                links: &p.links,
            })?;
            report.files += 1;
        }
    }
    if let Some(dim) = report.embed_dim {
        store.set_meta("embed_dim", &dim.to_string())?;
    }
    if let Some(model) = report.embed_model.as_deref() {
        store.set_meta("embed_model", model)?;
    }
    store.touch()?;
    Ok(report)
}

/// Export this store back to the same JSONL shape, so the Python build can
/// read a native index if someone migrates the other direction.
pub fn export(store: &Store, out: &Path) -> Result<usize> {
    let mut f = std::io::BufWriter::new(std::fs::File::create(out)?);
    let rows = store.dump_rows()?;
    for row in &rows {
        writeln!(f, "{row}")?;
    }
    let meta = serde_json::json!({
        "__meta__": {
            "chunks": rows.len(),
            "embed_model": store.meta("embed_model")?,
            "embed_dim": store.meta("embed_dim")?.and_then(|d| d.parse::<usize>().ok()),
        }
    });
    writeln!(f, "{meta}")?;
    f.flush()?;
    Ok(rows.len())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn temp() -> std::path::PathBuf {
        use std::sync::atomic::{AtomicU64, Ordering};
        static SEQ: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "loci-migrate-{}-{}",
            std::process::id(),
            SEQ.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn store_at(dir: &Path) -> Store {
        Store::open(dir.join("index.db")).unwrap()
    }

    fn export_with(dir: &Path, model: &str, dim: usize) -> std::path::PathBuf {
        let p = dir.join("export.jsonl");
        let mut f = std::fs::File::create(&p).unwrap();
        for (i, (src, text, section)) in [
            ("/notes/a.md", "the humidity sensor is SHT45", "ADR-001"),
            ("/notes/a.md", "second chunk of the same file", ""),
            ("/notes/b.md", "wifi retries cost power", "Retro"),
        ]
        .iter()
        .enumerate()
        {
            let v: Vec<f32> = (0..dim).map(|k| if k == i { 1.0 } else { 0.0 }).collect();
            writeln!(
                f,
                "{}",
                serde_json::json!({
                    "id": format!("{src}::{i}"), "source": src, "chunk": i,
                    "section": section, "text": text, "hash": "abc123",
                    "chash": format!("c{i}"), "tags": "test", "mtime": 1.5,
                    "vec": v
                })
            )
            .unwrap();
        }
        writeln!(
            f,
            "{}",
            serde_json::json!({"__meta__": {"chunks": 3, "embed_model": model, "embed_dim": dim}})
        )
        .unwrap();
        p
    }

    #[test]
    fn imports_chunks_grouped_by_file() {
        let dir = temp();
        let store = store_at(&dir);
        let path = export_with(&dir, "text-embedding-3-small", 4);
        let r = import(&store, &path, Some("text-embedding-3-small"), false).unwrap();
        assert_eq!(r.chunks, 3);
        assert_eq!(r.files, 2);
        assert_eq!(store.count().unwrap(), 3);
        // two chunks of a.md, one of b.md
        let per = store.per_source().unwrap();
        assert_eq!(per["/notes/a.md"], 2);
        assert_eq!(per["/notes/b.md"], 1);
    }

    #[test]
    fn keeps_the_file_hash_so_the_next_ingest_skips() {
        let dir = temp();
        let store = store_at(&dir);
        let path = export_with(&dir, "m", 2);
        import(&store, &path, None, false).unwrap();
        assert_eq!(store.indexed_hash("/notes/a.md").unwrap().as_deref(), Some("abc123"));
    }

    #[test]
    fn refuses_a_different_embedding_model() {
        let dir = temp();
        let store = store_at(&dir);
        let path = export_with(&dir, "text-embedding-3-small", 3);
        let err = import(&store, &path, Some("bge-m3"), false).unwrap_err();
        let msg = format!("{err:#}");
        assert!(msg.contains("embedding model"), "{msg}");
        // nothing was written
        assert_eq!(store.count().unwrap(), 0);
    }

    #[test]
    fn force_imports_across_models() {
        let dir = temp();
        let store = store_at(&dir);
        let path = export_with(&dir, "text-embedding-3-small", 3);
        let r = import(&store, &path, Some("bge-m3"), true).unwrap();
        assert_eq!(r.chunks, 3);
        assert_eq!(store.count().unwrap(), 3);
    }

    #[test]
    fn skips_rows_without_source_or_vector() {
        let dir = temp();
        let store = store_at(&dir);
        let p = dir.join("bad.jsonl");
        let mut f = std::fs::File::create(&p).unwrap();
        writeln!(f, "{}", serde_json::json!({"source": "", "vec": [1.0]})).unwrap();
        writeln!(f, "{}", serde_json::json!({"source": "/x.md", "text": "no vector"})).unwrap();
        writeln!(f, "{}", serde_json::json!({"source": "/y.md", "vec": [1.0, 0.0], "text": "ok"})).unwrap();
        let r = import(&store, &p, None, false).unwrap();
        assert_eq!(r.skipped, 2);
        assert_eq!(r.chunks, 1);
        assert_eq!(store.count().unwrap(), 1);
    }

    #[test]
    fn records_the_embedding_fingerprint() {
        let dir = temp();
        let store = store_at(&dir);
        let path = export_with(&dir, "text-embedding-3-small", 5);
        import(&store, &path, None, false).unwrap();
        assert_eq!(store.meta("embed_model").unwrap().as_deref(),
                   Some("text-embedding-3-small"));
        assert_eq!(store.meta("embed_dim").unwrap().as_deref(), Some("5"));
    }

    #[test]
    fn round_trips_through_export() {
        let dir = temp();
        let store = store_at(&dir);
        let path = export_with(&dir, "m", 3);
        import(&store, &path, None, false).unwrap();

        let out = dir.join("again.jsonl");
        let n = export(&store, &out).unwrap();
        assert_eq!(n, 3);

        let second = Store::open(dir.join("second.db")).unwrap();
        let r = import(&second, &out, Some("m"), false).unwrap();
        assert_eq!(r.chunks, 3);
        assert_eq!(second.count().unwrap(), 3);
    }
}
