//! Chunk store on SQLite: one row per chunk with its vector as a BLOB.
//!
//! Chroma was the reason the Python build needed a 40 MB native dependency and
//! a first-run telemetry opt-out. For a personal knowledge base the corpus is
//! tens of thousands of chunks at most, so a brute-force cosine over a
//! contiguous float array is both simpler and fast enough — and it makes the
//! whole index one portable file.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use rusqlite::{params, Connection};

#[derive(Debug, Clone)]
pub struct StoredChunk {
    pub id: String,
    pub source: String,
    pub chunk: u32,
    pub section: String,
    pub text: String,
    pub tags: String,
    pub mtime: f64,
    pub distance: Option<f32>,
}

pub struct Store {
    conn: Connection,
    path: PathBuf,
}

/// One file's worth of chunks, as handed to [`Store::upsert_source`].
pub struct SourceWrite<'a> {
    pub source: &'a str,
    pub file_hash: &'a str,
    pub mtime: f64,
    pub tags: &'a str,
    /// (text, heading breadcrumb)
    pub chunks: &'a [(String, String)],
    pub chashes: &'a [String],
    pub vectors: &'a [Vec<f32>],
}

fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn f32_to_blob(v: &[f32]) -> Vec<u8> {
    let mut out = Vec::with_capacity(v.len() * 4);
    for x in v {
        out.extend_from_slice(&x.to_le_bytes());
    }
    out
}

fn blob_to_f32(b: &[u8]) -> Vec<f32> {
    // little-endian f32 per vector element; trailing bytes cannot occur because
    // f32_to_blob wrote them, but ignoring a partial tail beats panicking
    b.as_chunks::<4>()
        .0
        .iter()
        .map(|c| f32::from_le_bytes(*c))
        .collect()
}

impl Store {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir).with_context(|| format!("create {dir:?}"))?;
        }
        let conn = Connection::open(&path).context("open store")?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS chunks (
                id      TEXT PRIMARY KEY,
                source  TEXT NOT NULL,
                chunk   INTEGER NOT NULL,
                section TEXT NOT NULL DEFAULT '',
                text    TEXT NOT NULL,
                tags    TEXT NOT NULL DEFAULT '',
                mtime   REAL NOT NULL DEFAULT 0,
                hash    TEXT NOT NULL DEFAULT '',
                chash   TEXT NOT NULL DEFAULT '',
                vec     BLOB NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                hash TEXT NOT NULL,
                mtime REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                val TEXT NOT NULL
            );
            "#,
        )?;
        Ok(Self { conn, path })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn count(&self) -> Result<usize> {
        let n: i64 = self
            .conn
            .query_row("SELECT COUNT(*) FROM chunks", [], |r| r.get(0))?;
        Ok(n as usize)
    }

    pub fn indexed_hash(&self, path: &str) -> Result<Option<String>> {
        let mut stmt = self.conn.prepare("SELECT hash FROM files WHERE path = ?1")?;
        let mut rows = stmt.query(params![path])?;
        Ok(match rows.next()? {
            Some(r) => Some(r.get(0)?),
            None => None,
        })
    }

    pub fn sources(&self) -> Result<Vec<String>> {
        let mut stmt = self
            .conn
            .prepare("SELECT DISTINCT source FROM chunks ORDER BY source")?;
        let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn per_source(&self) -> Result<HashMap<String, usize>> {
        let mut stmt = self
            .conn
            .prepare("SELECT source, COUNT(*) FROM chunks GROUP BY source")?;
        let rows = stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))?;
        let mut out = HashMap::new();
        for row in rows {
            let (src, n) = row?;
            out.insert(src, n as usize);
        }
        Ok(out)
    }

    pub fn delete_source(&self, source: &str) -> Result<()> {
        self.conn.execute("DELETE FROM chunks WHERE source = ?1", params![source])?;
        self.conn.execute("DELETE FROM files WHERE path = ?1", params![source])?;
        Ok(())
    }

    /// Replace every chunk of `source`. Idempotent: re-indexing a file never
    /// leaves duplicates behind.
    pub fn upsert_source(&self, doc: &SourceWrite<'_>) -> Result<usize> {
        let SourceWrite { source, file_hash, mtime, tags, chunks, chashes, vectors } = doc;
        // &self on purpose: rusqlite's unchecked_transaction only needs a
        // shared connection, and this keeps the store shareable behind Arc
        let tx = self.conn.unchecked_transaction()?;
        tx.execute("DELETE FROM chunks WHERE source = ?1", params![source])?;
        {
            let mut stmt = tx.prepare(
                "INSERT INTO chunks (id, source, chunk, section, text, tags, mtime, hash, chash, vec)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
            )?;
            for (i, (text, section)) in chunks.iter().enumerate() {
                let id = format!("{source}::{i}");
                stmt.execute(params![
                    id,
                    source,
                    i as i64,
                    section,
                    text,
                    tags,
                    mtime,
                    file_hash,
                    chashes.get(i).cloned().unwrap_or_default(),
                    f32_to_blob(&vectors[i])
                ])?;
            }
        }
        tx.execute(
            "INSERT INTO files (path, hash, mtime) VALUES (?1, ?2, ?3)
             ON CONFLICT(path) DO UPDATE SET hash = excluded.hash, mtime = excluded.mtime",
            params![source, file_hash, mtime],
        )?;
        tx.commit()?;
        Ok(chunks.len())
    }

    /// Existing chunk texts for a file, keyed by content hash, so an unchanged
    /// chunk keeps its vector on re-index.
    pub fn reuse_map(&self, source: &str) -> Result<HashMap<String, Vec<f32>>> {
        let mut stmt = self
            .conn
            .prepare("SELECT chash, vec FROM chunks WHERE source = ?1")?;
        let rows = stmt.query_map(params![source], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, Vec<u8>>(1)?))
        })?;
        let mut out = HashMap::new();
        for row in rows {
            let (chash, blob) = row?;
            if !chash.is_empty() {
                out.insert(chash, blob_to_f32(&blob));
            }
        }
        Ok(out)
    }

    /// All chunks as (id, text) — the corpus the BM25 side is built over.
    pub fn all_texts(&self) -> Result<Vec<(String, String)>> {
        let mut stmt = self.conn.prepare("SELECT id, text FROM chunks")?;
        let rows = stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Brute-force cosine. Vectors are stored L2-normalized by the embedder, so
    /// a dot product is the cosine similarity.
    pub fn vector_search(&self, query: &[f32], limit: usize) -> Result<Vec<StoredChunk>> {
        let mut stmt = self.conn.prepare(
            "SELECT id, source, chunk, section, text, tags, mtime, vec FROM chunks",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, String>(4)?,
                r.get::<_, String>(5)?,
                r.get::<_, f64>(6)?,
                r.get::<_, Vec<u8>>(7)?,
            ))
        })?;

        let mut scored: Vec<(f32, StoredChunk)> = Vec::new();
        for row in rows {
            let (id, source, chunk, section, text, tags, mtime, blob) = row?;
            let v = blob_to_f32(&blob);
            if v.len() != query.len() {
                continue; // different embedding model; the fingerprint check catches it
            }
            let dot: f32 = v.iter().zip(query).map(|(a, b)| a * b).sum();
            scored.push((
                dot,
                StoredChunk {
                    id,
                    source,
                    chunk: chunk as u32,
                    section,
                    text,
                    tags,
                    mtime,
                    distance: Some(1.0 - dot),
                },
            ));
        }
        scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
        Ok(scored.into_iter().take(limit).map(|(_, c)| c).collect())
    }

    /// Every chunk as an export row (JSON value), for `loci export`.
    pub fn dump_rows(&self) -> Result<Vec<serde_json::Value>> {
        let mut stmt = self.conn.prepare(
            "SELECT id, source, chunk, section, text, tags, mtime, hash, chash, vec
             FROM chunks ORDER BY source, chunk",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, i64>(2)?,
                r.get::<_, String>(3)?, r.get::<_, String>(4)?, r.get::<_, String>(5)?,
                r.get::<_, f64>(6)?, r.get::<_, String>(7)?, r.get::<_, String>(8)?,
                r.get::<_, Vec<u8>>(9)?,
            ))
        })?;
        let mut out = Vec::new();
        for row in rows {
            let (id, source, chunk, section, text, tags, mtime, hash, chash, blob) = row?;
            let vec: Vec<f32> = blob_to_f32(&blob);
            out.push(serde_json::json!({
                "id": id, "source": source, "chunk": chunk, "section": section,
                "text": text, "tags": tags, "mtime": mtime, "hash": hash,
                "chash": chash, "vec": vec,
            }));
        }
        Ok(out)
    }

    pub fn get_many(&self, ids: &[String]) -> Result<Vec<StoredChunk>> {
        let mut out = Vec::new();
        let mut stmt = self.conn.prepare(
            "SELECT id, source, chunk, section, text, tags, mtime FROM chunks WHERE id = ?1",
        )?;
        for id in ids {
            let mut rows = stmt.query(params![id])?;
            if let Some(r) = rows.next()? {
                out.push(StoredChunk {
                    id: r.get(0)?,
                    source: r.get(1)?,
                    chunk: r.get::<_, i64>(2)? as u32,
                    section: r.get(3)?,
                    text: r.get(4)?,
                    tags: r.get(5)?,
                    mtime: r.get(6)?,
                    distance: None,
                });
            }
        }
        Ok(out)
    }

    // ---- embedding-space fingerprint ----

    pub fn set_meta(&self, key: &str, val: &str) -> Result<()> {
        self.conn.execute(
            "INSERT INTO meta (key, val) VALUES (?1, ?2)
             ON CONFLICT(key) DO UPDATE SET val = excluded.val",
            params![key, val],
        )?;
        Ok(())
    }

    pub fn meta(&self, key: &str) -> Result<Option<String>> {
        let mut stmt = self.conn.prepare("SELECT val FROM meta WHERE key = ?1")?;
        let mut rows = stmt.query(params![key])?;
        Ok(match rows.next()? {
            Some(r) => Some(r.get(0)?),
            None => None,
        })
    }

    pub fn touch(&self) -> Result<()> {
        self.set_meta("updated_at", &now().to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn store() -> Store {
        // unique per call: tests in one binary run concurrently, and a shared
        // path made them see each other's rows
        use std::sync::atomic::{AtomicU64, Ordering};
        static SEQ: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "loci-store-{}-{}",
            std::process::id(),
            SEQ.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&dir);
        Store::open(dir.join("index.db")).unwrap()
    }

    fn vec(v: &[f32]) -> Vec<f32> {
        let n = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        if n == 0.0 { v.to_vec() } else { v.iter().map(|x| x / n).collect() }
    }

    #[test]
    fn upsert_replaces_instead_of_duplicating() {
        let s = store();
        let chunks = vec![("a".to_string(), "S".to_string())];
        for h in ["h1", "h2"] {
            s.upsert_source(&SourceWrite {
                source: "/f.md", file_hash: h, mtime: 0.0, tags: "",
                chunks: &chunks, chashes: &["c1".to_string()],
                vectors: &[vec(&[1.0, 0.0])],
            }).unwrap();
        }
        assert_eq!(s.count().unwrap(), 1);
        assert_eq!(s.indexed_hash("/f.md").unwrap().as_deref(), Some("h2"));
    }

    #[test]
    fn vector_search_orders_by_similarity() {
        let s = store();
        let a_chunks = vec![("x".to_string(), String::new())];
        s.upsert_source(&SourceWrite {
            source: "/a.md", file_hash: "h", mtime: 0.0, tags: "",
            chunks: &a_chunks, chashes: &["c".to_string()], vectors: &[vec(&[1.0, 0.0])],
        }).unwrap();
        let b_chunks = vec![("y".to_string(), String::new())];
        s.upsert_source(&SourceWrite {
            source: "/b.md", file_hash: "h", mtime: 0.0, tags: "",
            chunks: &b_chunks, chashes: &["c".to_string()], vectors: &[vec(&[0.0, 1.0])],
        }).unwrap();
        let hits = s.vector_search(&vec(&[0.9, 0.1]), 2).unwrap();
        assert_eq!(hits[0].source, "/a.md");
        assert!(hits[0].distance.unwrap() < hits[1].distance.unwrap());
    }

    #[test]
    fn reuse_map_survives_reindex() {
        let s = store();
        let chunks = vec![("x".to_string(), String::new())];
        s.upsert_source(&SourceWrite {
            source: "/a.md", file_hash: "h", mtime: 0.0, tags: "",
            chunks: &chunks, chashes: &["chash1".to_string()], vectors: &[vec(&[1.0, 0.0])],
        }).unwrap();
        let map = s.reuse_map("/a.md").unwrap();
        assert!(map.contains_key("chash1"));
        assert_eq!(map["chash1"], vec![1.0, 0.0]);
    }

    #[test]
    fn per_source_counts_and_delete() {
        let s = store();
        let chunks = vec![("x".to_string(), String::new()), ("y".to_string(), String::new())];
        s.upsert_source(&SourceWrite {
            source: "/a.md", file_hash: "h", mtime: 0.0, tags: "",
            chunks: &chunks, chashes: &["1".to_string(), "2".to_string()],
            vectors: &[vec(&[1.0, 0.0]), vec(&[1.0, 0.0])],
        }).unwrap();
        assert_eq!(s.per_source().unwrap()["/a.md"], 2);
        s.delete_source("/a.md").unwrap();
        assert_eq!(s.count().unwrap(), 0);
        assert!(s.indexed_hash("/a.md").unwrap().is_none());
    }

    #[test]
    fn mismatched_dimensions_are_skipped_not_fatal() {
        let s = store();
        let chunks = vec![("x".to_string(), String::new())];
        s.upsert_source(&SourceWrite {
            source: "/a.md", file_hash: "h", mtime: 0.0, tags: "",
            chunks: &chunks, chashes: &["c".to_string()], vectors: &[vec(&[1.0, 0.0])],
        }).unwrap();
        let hits = s.vector_search(&vec(&[1.0, 0.0, 0.0]), 5).unwrap();
        assert!(hits.is_empty());
    }
}
