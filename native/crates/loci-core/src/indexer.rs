//! Incremental indexing: scan sources, skip files whose content hash is
//! unchanged, reuse vectors for chunks that did not change, prune files that
//! disappeared. Same contract as `loci ingest`, so a re-run is cheap and safe.

use std::collections::{HashMap, HashSet};
use std::path::Path;

use anyhow::Result;

use crate::chunker::{split_markdown, ChunkParams};
use crate::config::Config;
use crate::embed::Embedder;
use crate::loader::{chunk_hash, scan_root, Document};
use crate::store::Store;

#[derive(Debug, Default)]
pub struct IngestReport {
    pub added: usize,
    pub updated: usize,
    pub skipped: usize,
    pub pruned: Vec<String>,
    pub chunks: usize,
    pub reused_vectors: usize,
}

/// Expand `[[sources]]` entries plus harness memory roots into documents.
pub fn collect_documents(cfg: &Config) -> Vec<Document> {
    let mut docs = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();

    for source in &cfg.sources {
        for doc in scan_root(Path::new(&source.path)) {
            let key = doc.path.to_string_lossy().to_string();
            if seen.insert(key) {
                docs.push(doc);
            }
        }
    }
    for harness in &cfg.harness {
        for path in &harness.paths {
            for doc in scan_root(Path::new(path)) {
                let key = doc.path.to_string_lossy().to_string();
                if seen.insert(key) {
                    docs.push(doc);
                }
            }
        }
    }
    docs
}

pub fn ingest(
    cfg: &Config,
    store: &mut Store,
    embedder: &dyn Embedder,
    force: bool,
) -> Result<IngestReport> {
    // Missing vaults must not look like deleted documents to the prune step.
    for source in &cfg.sources {
        if !Path::new(&source.path).is_dir() {
            anyhow::bail!("source directory unavailable; index left unchanged: {}", source.path);
        }
    }
    let mut report = IngestReport::default();
    let docs = collect_documents(cfg);
    let keep: HashSet<String> = docs
        .iter()
        .map(|d| d.path.to_string_lossy().to_string())
        .collect();

    // prune files that no longer exist before indexing, so a moved file does
    // not leave its old chunks behind
    let existing = store.sources()?;
    for gone in existing.iter().filter(|s| !keep.contains(*s)) {
        store.delete_source(gone)?;
        report.pruned.push(gone.clone());
    }

    for doc in &docs {
        let path = doc.path.to_string_lossy().to_string();
        if !force {
            if let Some(hash) = store.indexed_hash(&path)? {
                if hash == doc.hash {
                    report.skipped += 1;
                    continue;
                }
                report.updated += 1;
            } else {
                report.added += 1;
            }
        } else {
            report.added += 1;
        }

        let (size, overlap) = chunk_params(cfg, &path);
        let chunks = split_markdown(&doc.body, ChunkParams { size, overlap });
        if chunks.is_empty() {
            store.delete_source(&path)?;
            continue;
        }

        let texts: Vec<String> = chunks.iter().map(|c| c.text.clone()).collect();
        let chashes: Vec<String> = texts.iter().map(|t| chunk_hash(t)).collect();

        // reuse vectors for unchanged chunks: a lightly edited file should not
        // re-embed the whole thing
        let existing_map: HashMap<String, Vec<f32>> = store.reuse_map(&path)?.into_iter().collect();
        let mut vectors: Vec<Option<Vec<f32>>> = chashes
            .iter()
            .map(|h| existing_map.get(h).cloned())
            .collect();
        let missing: Vec<usize> = vectors
            .iter()
            .enumerate()
            .filter(|(_, v)| v.is_none())
            .map(|(i, _)| i)
            .collect();
        report.reused_vectors += chashes.len() - missing.len();

        if !missing.is_empty() {
            let to_embed: Vec<String> = missing.iter().map(|i| texts[*i].clone()).collect();
            let fresh = embedder.embed(&to_embed)?;
            if fresh.len() != missing.len() {
                anyhow::bail!(
                    "embedder returned {} vectors for {} inputs",
                    fresh.len(),
                    missing.len()
                );
            }
            for (slot, vec) in missing.iter().zip(fresh) {
                vectors[*slot] = Some(vec);
            }
        }

        let final_vectors: Vec<Vec<f32>> = vectors.into_iter().map(|v| v.unwrap_or_default()).collect();
        let pairs: Vec<(String, String)> = chunks
            .iter()
            .map(|c| (c.text.clone(), c.section.clone()))
            .collect();
        let n = store.upsert_source(&crate::store::SourceWrite {
            source: &path,
            file_hash: &doc.hash,
            mtime: doc.mtime,
            tags: &doc.tags,
            chunks: &pairs,
            chashes: &chashes,
            vectors: &final_vectors,
        })?;
        report.chunks += n;
    }

    if let Some(first) = docs.first() {
        let dims = embedder.embed(&[first.body.chars().take(64).collect::<String>()])?;
        if let Some(v) = dims.first() {
            store.set_meta("embed_model", embedder.model())?;
            store.set_meta("embed_dim", &v.len().to_string())?;
        }
    }
    store.touch()?;
    Ok(report)
}

fn chunk_params(cfg: &Config, path: &str) -> (usize, usize) {
    for source in &cfg.sources {
        if path.starts_with(&source.path) {
            return (
                source.chunk_size.unwrap_or(cfg.chunk.size),
                source.chunk_overlap.unwrap_or(cfg.chunk.overlap),
            );
        }
    }
    (cfg.chunk.size, cfg.chunk.overlap)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::embed::HashEmbedder;

    fn tempdir(tag: &str) -> std::path::PathBuf {
        use std::sync::atomic::{AtomicU64, Ordering};
        static SEQ: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "loci-idx-{tag}-{}-{}",
            std::process::id(),
            SEQ.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn setup() -> (std::path::PathBuf, Config, Store, HashEmbedder) {
        let dir = tempdir("src");
        std::fs::write(dir.join("a.md"), "# A\n\nhumidity sensor decision").unwrap();
        std::fs::write(dir.join("b.md"), "# B\n\nwifi retries and power").unwrap();
        let mut cfg = Config::default();
        cfg.embed.api_key = "test".into();
        cfg.sources.push(crate::config::SourceConfig {
            path: dir.to_string_lossy().to_string(),
            chunk_size: None,
            chunk_overlap: None,
        });
        let store = Store::open(dir.join("index.db")).unwrap();
        (dir, cfg, store, HashEmbedder::default())
    }

    #[test]
    fn first_run_indexes_everything() {
        let (_dir, cfg, mut store, emb) = setup();
        let r = ingest(&cfg, &mut store, &emb, false).unwrap();
        assert_eq!(r.added, 2);
        assert_eq!(store.count().unwrap(), 2);
    }

    #[test]
    fn second_run_skips_unchanged_files() {
        let (_dir, cfg, mut store, emb) = setup();
        ingest(&cfg, &mut store, &emb, false).unwrap();
        let r = ingest(&cfg, &mut store, &emb, false).unwrap();
        assert_eq!(r.skipped, 2);
        assert_eq!(r.added, 0);
        assert_eq!(store.count().unwrap(), 2);
    }

    #[test]
    fn edited_file_is_updated_and_old_chunks_replaced() {
        let (dir, cfg, mut store, emb) = setup();
        ingest(&cfg, &mut store, &emb, false).unwrap();
        std::fs::write(dir.join("a.md"), "# A\n\ncompletely different content").unwrap();
        let r = ingest(&cfg, &mut store, &emb, false).unwrap();
        assert_eq!(r.updated, 1);
        assert_eq!(store.count().unwrap(), 2, "no duplicate rows");
    }

    #[test]
    fn deleted_file_is_pruned() {
        let (dir, cfg, mut store, emb) = setup();
        ingest(&cfg, &mut store, &emb, false).unwrap();
        std::fs::remove_file(dir.join("b.md")).unwrap();
        let r = ingest(&cfg, &mut store, &emb, false).unwrap();
        assert_eq!(r.pruned.len(), 1);
        assert_eq!(store.count().unwrap(), 1);
    }

    #[test]
    fn missing_source_does_not_prune_existing_index() {
        let (dir, cfg, mut store, emb) = setup();
        ingest(&cfg, &mut store, &emb, false).unwrap();
        let moved = dir.with_extension("offline");
        std::fs::rename(&dir, &moved).unwrap();
        let error = ingest(&cfg, &mut store, &emb, false).unwrap_err();
        assert!(error.to_string().contains("index left unchanged"));
        assert_eq!(store.count().unwrap(), 2);
        std::fs::rename(&moved, &dir).unwrap();
    }

    #[test]
    fn unchanged_chunks_reuse_their_vectors() {
        let (dir, cfg, mut store, emb) = setup();
        ingest(&cfg, &mut store, &emb, false).unwrap();
        // append a section: the first chunk is unchanged
        let mut text = std::fs::read_to_string(dir.join("a.md")).unwrap();
        text.push_str("\n\n## Extra\n\nmore notes here");
        std::fs::write(dir.join("a.md"), text).unwrap();
        let r = ingest(&cfg, &mut store, &emb, false).unwrap();
        assert!(r.reused_vectors >= 1, "{r:?}");
    }

    #[test]
    fn embedding_fingerprint_is_recorded() {
        let (_dir, cfg, mut store, emb) = setup();
        ingest(&cfg, &mut store, &emb, false).unwrap();
        assert_eq!(store.meta("embed_model").unwrap().as_deref(), Some("hash-64"));
    }
}
