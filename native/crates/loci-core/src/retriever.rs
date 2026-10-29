//! Hybrid retrieval: vector recall fused with BM25 over Reciprocal Rank Fusion.
//!
//! RRF is used instead of score addition because the two halves are not
//! commensurable — cosine distance is bounded, BM25 is not — so only the rank
//! within each list is trusted. `rrf_k` = 60 is the constant from the original
//! paper and matches the Python implementation, so rankings survive migration.

use std::collections::HashMap;

use anyhow::Result;

use crate::bm25::{Bm25Index, Bm25Params};
use crate::embed::Embedder;
use crate::store::{Store, StoredChunk};
use crate::tokenizer::Tokenizer;

#[derive(Debug, Clone)]
pub struct RetrievalConfig {
    pub top_k: usize,
    pub hybrid: bool,
    /// Rank by BM25 alone. For the offline demo (the hash embedder measures
    /// token overlap, not meaning — calling that "vector search" would be a
    /// claim it cannot back) and for users who want pure keyword retrieval.
    pub lexical_only: bool,
    pub rrf_k: f64,
    pub tokenizer: Tokenizer,
    /// Chunks retained per query across both halves before truncation.
    pub fetch_factor: usize,
}

impl Default for RetrievalConfig {
    fn default() -> Self {
        Self {
            top_k: 5,
            hybrid: true,
            lexical_only: false,
            rrf_k: 60.0,
            tokenizer: Tokenizer::Default,
            fetch_factor: 4,
        }
    }
}

/// One fused hit, carrying everything a citation needs.
#[derive(Debug, Clone)]
pub struct Hit {
    pub id: String,
    pub source: String,
    pub section: String,
    pub text: String,
    pub tags: String,
    pub distance: Option<f32>,
    /// Rank-based fusion score; higher is better, not comparable across queries.
    pub score: f64,
}

#[derive(Debug, Clone, Default)]
pub struct Filters {
    pub tag: Option<String>,
    pub path_contains: Option<String>,
    pub since: Option<f64>,
}

impl Filters {
    pub fn is_empty(&self) -> bool {
        self.tag.is_none() && self.path_contains.is_none() && self.since.is_none()
    }

    fn matches(&self, h: &StoredChunk) -> bool {
        if let Some(tag) = &self.tag {
            // exact membership, not substring: `--tag rag` must not hit "storage"
            let want = tag.to_lowercase();
            let hit = h
                .tags
                .split(',')
                .any(|t| t.trim().to_lowercase() == want);
            if !hit {
                return false;
            }
        }
        if let Some(p) = &self.path_contains {
            let needle = p.to_lowercase().replace('\\', "/");
            if !h.source.to_lowercase().replace('\\', "/").contains(&needle) {
                return false;
            }
        }
        if let Some(since) = self.since {
            if h.mtime < since {
                return false;
            }
        }
        true
    }
}

pub struct Retriever<'a> {
    store: &'a Store,
    embedder: &'a dyn Embedder,
    cfg: RetrievalConfig,
    /// BM25 over the whole corpus, built lazily and reused while the store is
    /// unchanged — rebuilding it per query was the single biggest cost in the
    /// Python implementation.
    bm25: Option<Bm25Index>,
    bm25_key: Option<usize>,
}

impl<'a> Retriever<'a> {
    pub fn new(store: &'a Store, embedder: &'a dyn Embedder, cfg: RetrievalConfig) -> Self {
        Self { store, embedder, cfg, bm25: None, bm25_key: None }
    }

    /// Drop the cached lexical index; call after any write to the store.
    pub fn invalidate(&mut self) {
        self.bm25 = None;
        self.bm25_key = None;
    }

    /// Lexical ranking for `query`, rebuilding the index only when the corpus
    /// size changed. Returns owned pairs so callers do not hold a borrow.
    fn lexical_score(&mut self, query: &str) -> Result<Vec<(String, f64)>> {
        let count = self.store.count()?;
        let stale = self.bm25.is_none() || self.bm25_key != Some(count);
        let tokenizer = self.cfg.tokenizer;
        if stale {
            let docs = self.store.all_texts()?;
            self.bm25 = Some(Bm25Index::build(
                docs.iter().map(|(id, t)| (id.as_str(), t.as_str())),
                tokenizer,
                Bm25Params::default(),
            ));
            self.bm25_key = Some(count);
        }
        Ok(self
            .bm25
            .as_ref()
            .expect("just built")
            .score(query, tokenizer))
    }

    /// Reciprocal Rank Fusion over several ranked lists.
    fn fuse(&self, lists: &[Vec<(String, f64)>]) -> Vec<(String, f64)> {
        let mut scores: HashMap<String, f64> = HashMap::new();
        for list in lists {
            for (rank, (id, _)) in list.iter().enumerate() {
                *scores.entry(id.clone()).or_insert(0.0) += 1.0 / (self.cfg.rrf_k + rank as f64 + 1.0);
            }
        }
        let mut out: Vec<(String, f64)> = scores.into_iter().collect();
        out.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        out
    }

    pub fn search(&mut self, query: &str, filters: &Filters, k: Option<usize>) -> Result<Vec<Hit>> {
        let limit = k.unwrap_or(self.cfg.top_k);
        if query.trim().is_empty() || limit == 0 {
            return Ok(Vec::new());
        }
        let fetch = if self.cfg.hybrid || self.cfg.lexical_only || !filters.is_empty() {
            (limit * self.cfg.fetch_factor).max(1)
        } else {
            limit.max(1)
        };

        let mut by_id: HashMap<String, StoredChunk> = HashMap::new();
        let mut ranked_lists: Vec<Vec<(String, f64)>> = Vec::new();

        if self.cfg.lexical_only {
            // keyword-only: BM25 ranks, and the chunks themselves are pulled by
            // id — no embedding call, no vector half
            let lexical = self.lexical_score(query)?;
            let top: Vec<(String, f64)> = lexical.into_iter().take(fetch).collect();
            let ids: Vec<String> = top.iter().map(|(id, _)| id.clone()).collect();
            for chunk in self.store.get_many(&ids)? {
                by_id.insert(chunk.id.clone(), chunk);
            }
            ranked_lists.push(top);
        } else {
            let query_vec = self.embedder.embed(&[query.to_string()])?;
            let query_vec = query_vec
                .into_iter()
                .next()
                .ok_or_else(|| anyhow::anyhow!("embedder returned no vector"))?;

            let vector_hits = self.store.vector_search(&query_vec, fetch)?;
            by_id.extend(
                vector_hits
                    .iter()
                    .map(|h| (h.id.clone(), h.clone())),
            );
            ranked_lists.push(
                vector_hits
                    .iter()
                    .enumerate()
                    .map(|(r, h)| (h.id.clone(), -(r as f64)))
                    .collect(),
            );

            if self.cfg.hybrid {
                let lexical = self.lexical_score(query)?;
                let top: Vec<(String, f64)> = lexical.into_iter().take(fetch).collect();
                let missing: Vec<String> = top
                    .iter()
                    .filter(|(id, _)| !by_id.contains_key(id))
                    .map(|(id, _)| id.clone())
                    .collect();
                for chunk in self.store.get_many(&missing)? {
                    by_id.insert(chunk.id.clone(), chunk);
                }
                ranked_lists.push(top);
            }
        }

        let fused = self.fuse(&ranked_lists);
        let mut out = Vec::new();
        for (id, score) in fused {
            let Some(chunk) = by_id.get(&id) else { continue };
            if !filters.matches(chunk) {
                continue;
            }
            out.push(Hit {
                id: chunk.id.clone(),
                source: chunk.source.clone(),
                section: chunk.section.clone(),
                text: chunk.text.clone(),
                tags: chunk.tags.clone(),
                distance: chunk.distance,
                score,
            });
            if out.len() == limit {
                break;
            }
        }
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::embed::HashEmbedder;

    fn seeded() -> (Store, HashEmbedder) {
        use std::sync::atomic::{AtomicU64, Ordering};
        static SEQ: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "loci-ret-{}-{}",
            std::process::id(),
            SEQ.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&dir);
        let store = Store::open(dir.join("index.db")).unwrap();
        let emb = HashEmbedder::default();

        for (src, text, tags) in [
            ("/aurora/decisions.md", "the SHT45 replaced the BME280 for humidity accuracy", "aurora,hardware"),
            ("/aurora/notes.md", "wifi retries cost 120 mAh during the storm", "aurora,ops"),
            ("/reading/list.md", "a book about voltage references and grounding", "reading"),
        ] {
            let v = emb.embed(&[text.to_string()]).unwrap();
            let chunks = vec![(text.to_string(), "S".to_string())];
            store
                .upsert_source(&crate::store::SourceWrite {
                    source: src,
                    file_hash: "h",
                    mtime: 1_700_000_000.0,
                    tags,
                    chunks: &chunks,
                    chashes: &["c".to_string()],
                    links: &[],
                    vectors: &v,
                })
                .unwrap();
        }
        (store, emb)
    }

    #[test]
    fn finds_the_relevant_chunk() {
        let (store, emb) = seeded();
        let mut r = Retriever::new(&store, &emb, RetrievalConfig::default());
        let hits = r.search("SHT45 humidity", &Filters::default(), None).unwrap();
        assert!(!hits.is_empty());
        assert!(hits[0].source.contains("decisions"));
        assert_eq!(hits[0].section, "S");
    }

    #[test]
    fn tag_filter_is_exact_membership() {
        let (store, emb) = seeded();
        let mut r = Retriever::new(&store, &emb, RetrievalConfig::default());
        let f = Filters { tag: Some("ops".into()), ..Default::default() };
        let hits = r.search("wifi", &f, None).unwrap();
        assert!(!hits.is_empty());
        assert!(hits.iter().all(|h| h.tags.split(',').any(|t| t.trim() == "ops")));

        // "op" must not match "ops"
        let f = Filters { tag: Some("op".into()), ..Default::default() };
        assert!(r.search("wifi", &f, None).unwrap().is_empty());
    }

    #[test]
    fn path_filter_narrows() {
        let (store, emb) = seeded();
        let mut r = Retriever::new(&store, &emb, RetrievalConfig::default());
        let f = Filters { path_contains: Some("reading".into()), ..Default::default() };
        let hits = r.search("voltage", &f, None).unwrap();
        assert!(hits.iter().all(|h| h.source.contains("reading")));
    }

    #[test]
    fn k_limits_results() {
        let (store, emb) = seeded();
        let mut r = Retriever::new(&store, &emb, RetrievalConfig::default());
        assert!(r.search("a", &Filters::default(), Some(1)).unwrap().len() <= 1);
    }

    #[test]
    fn blank_query_returns_nothing() {
        let (store, emb) = seeded();
        let mut r = Retriever::new(&store, &emb, RetrievalConfig::default());
        assert!(r.search("   ", &Filters::default(), None).unwrap().is_empty());
    }

    #[test]
    fn vector_only_mode_still_works() {
        let (store, emb) = seeded();
        let cfg = RetrievalConfig { hybrid: false, ..Default::default() };
        let mut r = Retriever::new(&store, &emb, cfg);
        assert!(!r.search("SHT45", &Filters::default(), None).unwrap().is_empty());
    }

    #[test]
    fn cache_invalidates_when_corpus_changes() {
        let (store, emb) = seeded();
        // scope the retriever so the store can be written afterwards
        let first = {
            let mut r = Retriever::new(&store, &emb, RetrievalConfig::default());
            r.search("humidity", &Filters::default(), None).unwrap()
        };
        let v = emb
            .embed(&["a brand new note about humidity sensors".to_string()])
            .unwrap();
        let chunks = vec![(
            "a brand new note about humidity sensors".to_string(),
            String::new(),
        )];
        store
            .upsert_source(&crate::store::SourceWrite {
                source: "/new.md",
                file_hash: "h",
                mtime: 1.0,
                tags: "",
                chunks: &chunks,
                chashes: &["c".to_string()],
                vectors: &v,
                links: &[],
            })
            .unwrap();
        let second = {
            let mut r = Retriever::new(&store, &emb, RetrievalConfig::default());
            r.search("humidity", &Filters::default(), None).unwrap()
        };
        assert!(
            second.iter().any(|h| h.source == "/new.md"),
            "{first:?} {second:?}"
        );
    }
}
