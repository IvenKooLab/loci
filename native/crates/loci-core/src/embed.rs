//! Embeddings from any OpenAI-compatible endpoint. Batched, with a hard cap on
//! per-request items so a large ingest does not exceed provider limits.

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone)]
pub struct EmbedConfig {
    pub base_url: String,
    pub api_key: String,
    pub model: String,
    pub batch: usize,
}

impl Default for EmbedConfig {
    fn default() -> Self {
        Self {
            base_url: "https://api.openai.com/v1".into(),
            api_key: String::new(),
            model: "text-embedding-3-small".into(),
            batch: 16,
        }
    }
}

#[derive(Serialize)]
struct EmbedRequest<'a> {
    model: &'a str,
    input: &'a [String],
}

#[derive(Deserialize)]
struct EmbedResponse {
    data: Vec<EmbedDatum>,
}

#[derive(Deserialize)]
struct EmbedDatum {
    embedding: Vec<f32>,
}

pub trait Embedder: Send + Sync {
    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
    fn model(&self) -> &str;
}

pub struct HttpEmbedder {
    cfg: EmbedConfig,
    client: reqwest::blocking::Client,
}

impl HttpEmbedder {
    pub fn new(cfg: EmbedConfig) -> Result<Self> {
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(60))
            .build()
            .context("build http client")?;
        Ok(Self { cfg, client })
    }

    fn endpoint(&self) -> String {
        format!("{}/embeddings", self.cfg.base_url.trim_end_matches('/'))
    }
}

impl Embedder for HttpEmbedder {
    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let mut out = Vec::with_capacity(texts.len());
        for part in texts.chunks(self.cfg.batch.max(1)) {
            // newlines collapse and long strings shrink: providers reject both
            let input: Vec<String> = part
                .iter()
                .map(|t| t.replace('\n', " ").chars().take(4000).collect())
                .collect();
            let resp = self
                .client
                .post(self.endpoint())
                .bearer_auth(&self.cfg.api_key)
                .json(&EmbedRequest { model: &self.cfg.model, input: &input })
                .send()
                .context("embedding request")?
                .error_for_status()
                .context("embedding endpoint rejected the request")?
                .json::<EmbedResponse>()
                .context("parse embedding response")?;
            out.extend(resp.data.into_iter().map(|d| d.embedding));
        }
        Ok(out)
    }

    fn model(&self) -> &str {
        &self.cfg.model
    }
}

/// Deterministic offline embedder: token-hash bag of words, L2-normalized.
/// Used by `loci demo` and the test suite, never for a real index.
pub struct HashEmbedder {
    pub dim: usize,
    pub model: String,
}

impl Default for HashEmbedder {
    fn default() -> Self {
        Self { dim: 64, model: "hash-64".into() }
    }
}

impl Embedder for HashEmbedder {
    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let mut out = Vec::with_capacity(texts.len());
        for text in texts {
            let mut v = vec![0.0f32; self.dim];
            for tok in text.to_lowercase().split_whitespace() {
                let mut h: u64 = 0xcbf29ce484222325;
                for b in tok.as_bytes() {
                    h ^= *b as u64;
                    h = h.wrapping_mul(0x100000001b3);
                }
                v[(h as usize) % self.dim] += 1.0;
            }
            let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
            if norm > 0.0 {
                for x in v.iter_mut() {
                    *x /= norm;
                }
            }
            out.push(v);
        }
        Ok(out)
    }

    fn model(&self) -> &str {
        &self.model
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_embedder_is_deterministic_and_normalized() {
        let e = HashEmbedder::default();
        let a = e.embed(&["hello world".into()]).unwrap();
        let b = e.embed(&["hello world".into()]).unwrap();
        assert_eq!(a, b);
        let norm: f32 = a[0].iter().map(|x| x * x).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 1e-5);
    }

    #[test]
    fn hash_embedder_separates_unrelated_text() {
        let e = HashEmbedder::default();
        let v = e.embed(&["alpha beta".into(), "zzz unrelated".into()]).unwrap();
        let dot: f32 = v[0].iter().zip(&v[1]).map(|(a, b)| a * b).sum();
        assert!(dot.abs() < 0.5, "dot={dot}");
    }
}
