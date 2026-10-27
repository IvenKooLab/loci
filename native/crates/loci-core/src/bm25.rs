//! Okapi BM25 with the pluggable tokenizers above. Same constants as the Python
//! implementation (k1 = 1.5, b = 0.75) so rankings do not drift on migration.

use std::collections::HashMap;

use crate::tokenizer::Tokenizer;

#[derive(Debug, Clone, Copy)]
pub struct Bm25Params {
    pub k1: f64,
    pub b: f64,
}

impl Default for Bm25Params {
    fn default() -> Self {
        Self { k1: 1.5, b: 0.75 }
    }
}

#[derive(Debug, Default)]
pub struct Bm25Index {
    /// doc id -> term frequencies
    tf: Vec<HashMap<String, u32>>,
    /// doc id -> document length in tokens
    dl: Vec<u32>,
    df: HashMap<String, u32>,
    avgdl: f64,
    ids: Vec<String>,
    params: Bm25Params,
}

impl Bm25Index {
    pub fn build<'a, I>(docs: I, tokenizer: Tokenizer, params: Bm25Params) -> Self
    where
        I: IntoIterator<Item = (&'a str, &'a str)>,
    {
        let mut tf = Vec::new();
        let mut dl = Vec::new();
        let mut df: HashMap<String, u32> = HashMap::new();
        let mut ids = Vec::new();

        for (id, text) in docs {
            ids.push(id.to_string());
            let tokens = tokenizer.tokenize(text);
            let mut freq: HashMap<String, u32> = HashMap::new();
            for t in &tokens {
                *freq.entry(t.clone()).or_insert(0) += 1;
            }
            for term in freq.keys() {
                *df.entry(term.clone()).or_insert(0) += 1;
            }
            dl.push(tokens.len() as u32);
            tf.push(freq);
        }

        let n = dl.len();
        let avgdl = if n == 0 {
            0.0
        } else {
            dl.iter().map(|d| *d as f64).sum::<f64>() / n as f64
        };

        Self { tf, dl, df, avgdl, ids, params }
    }

    pub fn len(&self) -> usize {
        self.ids.len()
    }

    pub fn is_empty(&self) -> bool {
        self.ids.is_empty()
    }

    /// (doc id, score) sorted by descending score; zero-scoring docs dropped.
    pub fn score(&self, query: &str, tokenizer: Tokenizer) -> Vec<(String, f64)> {
        let n = self.ids.len() as f64;
        if n == 0.0 {
            return Vec::new();
        }
        let q_tokens = tokenizer.tokenize(query);
        let mut out: Vec<(String, f64)> = Vec::new();

        for (i, freq) in self.tf.iter().enumerate() {
            let dl = self.dl[i] as f64;
            if dl == 0.0 {
                continue;
            }
            let mut s = 0.0;
            for term in &q_tokens {
                let Some(&df) = self.df.get(term) else { continue };
                let Some(&tf) = freq.get(term) else { continue };
                let idf = (1.0 + (n - df as f64 + 0.5) / (df as f64 + 0.5)).ln();
                let tf = tf as f64;
                s += idf * tf * (self.params.k1 + 1.0)
                    / (tf + self.params.k1 * (1.0 - self.params.b
                        + self.params.b * dl / self.avgdl));
            }
            if s > 0.0 {
                out.push((self.ids[i].clone(), s));
            }
        }
        out.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn idx(docs: &[(&str, &str)], tok: Tokenizer) -> Bm25Index {
        Bm25Index::build(docs.iter().copied(), tok, Bm25Params::default())
    }

    #[test]
    fn relevant_document_ranks_first() {
        let i = idx(&[
            ("a", "the quick brown fox"),
            ("b", "vector embeddings for semantic search"),
            ("c", "gardening tips for tomatoes"),
        ], Tokenizer::Default);
        assert_eq!(i.score("vector semantic search", Tokenizer::Default)[0].0, "b");
    }

    #[test]
    fn single_char_tokenizer_lets_the_decoy_win() {
        // the regression the bigram tokenizer exists for
        let docs = [
            ("correct", "全文检索是知识库的核心能力"),
            ("decoy", "定期检查索引状态并重建"),
        ];
        let single = idx(&docs, Tokenizer::Default);
        let s: HashMap<_, _> = single.score("检索", Tokenizer::Default).into_iter().collect();
        assert!(s["decoy"] > s["correct"], "{s:?}");
    }

    #[test]
    fn bigram_tokenizer_fixes_the_decoy_and_keeps_recall() {
        let docs = [
            ("correct", "全文检索是知识库的核心能力"),
            ("decoy", "定期检查索引状态并重建"),
        ];
        let bigram = idx(&docs, Tokenizer::CjkBigram);
        let s: HashMap<_, _> = bigram.score("检索", Tokenizer::CjkBigram).into_iter().collect();
        assert!(s.contains_key("correct"));
        assert!(!s.contains_key("decoy"), "{s:?}");
    }

    #[test]
    fn empty_query_scores_nothing() {
        let i = idx(&[("a", "anything")], Tokenizer::Default);
        assert!(i.score("   ", Tokenizer::Default).is_empty());
    }

    #[test]
    fn no_documents_is_safe() {
        let i = idx(&[], Tokenizer::Default);
        assert!(i.is_empty());
        assert!(i.score("x", Tokenizer::Default).is_empty());
    }
}
