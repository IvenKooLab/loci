//! config.toml, parsed with the same shape as the Python build so an existing
//! instance directory keeps working after the migration.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

use crate::tokenizer::Tokenizer;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmConfig {
    #[serde(default)]
    pub base_url: String,
    #[serde(default)]
    pub api_key: String,
    #[serde(default)]
    pub model: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceConfig {
    pub path: String,
    #[serde(default)]
    pub chunk_size: Option<usize>,
    #[serde(default)]
    pub chunk_overlap: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkConfig {
    #[serde(default = "default_chunk_size")]
    pub size: usize,
    #[serde(default = "default_overlap")]
    pub overlap: usize,
}

fn default_chunk_size() -> usize { 800 }
fn default_overlap() -> usize { 100 }

impl Default for ChunkConfig {
    fn default() -> Self {
        Self { size: default_chunk_size(), overlap: default_overlap() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RetrievalConfigFile {
    #[serde(default = "yes")]
    pub hybrid: bool,
    #[serde(default = "default_rrf")]
    pub rrf_k: f64,
    #[serde(default = "default_top_k")]
    pub top_k: usize,
}

fn yes() -> bool { true }
fn default_rrf() -> f64 { 60.0 }
fn default_top_k() -> usize { 5 }

impl Default for RetrievalConfigFile {
    fn default() -> Self {
        Self { hybrid: true, rrf_k: 60.0, top_k: 5 }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Bm25Config {
    /// "default" | "cjk_bigram" | "hyphen_join"
    #[serde(default = "default_tokenizer_name")]
    pub tokenizer: String,
}

fn default_tokenizer_name() -> String { "default".into() }

impl Default for Bm25Config {
    fn default() -> Self {
        Self { tokenizer: default_tokenizer_name() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StoreConfig {
    #[serde(default = "default_store")]
    pub path: String,
}

fn default_store() -> String { "./index.db".into() }

impl Default for StoreConfig {
    fn default() -> Self {
        Self { path: default_store() }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct HttpConfig {
    /// Where harness logos live. A bare relative path means "in the instance"
    /// (beside the store), not "beside whatever directory we were started in".
    #[serde(default)]
    pub icons: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Config {
    #[serde(default)]
    pub llm: LlmConfig,
    #[serde(default)]
    pub embed: LlmConfig,
    #[serde(default)]
    pub chunk: ChunkConfig,
    #[serde(default)]
    pub retrieval: RetrievalConfigFile,
    #[serde(default)]
    pub bm25: Bm25Config,
    #[serde(default)]
    pub store: StoreConfig,
    #[serde(default)]
    pub sources: Vec<SourceConfig>,
    #[serde(default)]
    pub harness: Vec<HarnessEntry>,
    #[serde(default)]
    pub http: HttpConfig,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct HarnessEntry {
    pub name: String,
    #[serde(default)]
    pub r#type: String,
    #[serde(default)]
    pub paths: Vec<String>,
    #[serde(default)]
    pub display: String,
}

impl LlmConfig {
    fn with_defaults(mut self, base: &str, model: &str) -> Self {
        if self.base_url.is_empty() {
            self.base_url = base.into();
        }
        if self.model.is_empty() {
            self.model = model.into();
        }
        self
    }
}

impl Default for LlmConfig {
    fn default() -> Self {
        Self {
            base_url: "https://api.openai.com/v1".into(),
            api_key: String::new(),
            model: String::new(),
        }
    }
}

impl Config {
    pub fn load(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        let mut cfg: Config = if path.exists() {
            let text = std::fs::read_to_string(path)
                .with_context(|| format!("read {path:?}"))?;
            toml::from_str(&text).with_context(|| format!("parse {path:?}"))?
        } else {
            Config::default()
        };
        // provider defaults mirror the Python config: embed must be an
        // embedding model, llm defaults to the cheap chat model
        cfg.llm = cfg.llm.with_defaults("https://api.openai.com/v1", "gpt-4o-mini");
        cfg.embed = cfg
            .embed
            .with_defaults("https://api.openai.com/v1", "text-embedding-3-small");
        if let Ok(v) = std::env::var("BRAIN_LLM_API_KEY") {
            cfg.llm.api_key = v;
        }
        if let Ok(v) = std::env::var("BRAIN_EMBED_API_KEY") {
            cfg.embed.api_key = v;
        }
        Ok(cfg)
    }

    pub fn tokenizer(&self) -> Tokenizer {
        Tokenizer::from_name(&self.bm25.tokenizer).unwrap_or_default()
    }

    pub fn store_path(&self) -> PathBuf {
        PathBuf::from(&self.store.path)
    }

    /// Problems worth refusing to start for, in the order a user hits them.
    pub fn validate(&self) -> Vec<String> {
        let mut problems = Vec::new();
        if self.embed.api_key.is_empty() {
            problems.push("embed.api_key is not set (config.toml or BRAIN_EMBED_API_KEY)".to_string());
        }
        if self.sources.is_empty() && self.harness.is_empty() {
            problems.push("no sources configured — add at least one [[sources]] directory".to_string());
        }
        if Tokenizer::from_name(&self.bm25.tokenizer).is_none() {
            problems.push(format!(
                "bm25.tokenizer = {:?} is not one of {:?}",
                self.bm25.tokenizer,
                Tokenizer::names()
            ));
        }
        problems
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_match_the_python_build() {
        let cfg = Config::default();
        assert_eq!(cfg.chunk.size, 800);
        assert_eq!(cfg.chunk.overlap, 100);
        assert_eq!(cfg.retrieval.top_k, 5);
        assert_eq!(cfg.retrieval.rrf_k, 60.0);
        assert!(cfg.retrieval.hybrid);
        assert_eq!(cfg.bm25.tokenizer, "default");
    }

    #[test]
    fn parses_a_real_config() {
        let text = r#"
[embed]
api_key = "sk-x"
model = "text-embedding-3-small"

[bm25]
tokenizer = "cjk_bigram"

[[sources]]
path = "/notes"
chunk_size = 1200
"#;
        let cfg: Config = toml::from_str(text).unwrap();
        assert_eq!(cfg.tokenizer(), Tokenizer::CjkBigram);
        assert_eq!(cfg.sources[0].chunk_size, Some(1200));
        assert!(cfg.validate().is_empty());
    }

    #[test]
    fn unknown_tokenizer_is_reported() {
        let cfg: Config = toml::from_str("[bm25]\ntokenizer = \"nope\"\n").unwrap();
        let problems = cfg.validate();
        assert!(problems.iter().any(|p| p.contains("bm25.tokenizer")));
    }

    #[test]
    fn missing_key_and_sources_are_reported() {
        let cfg = Config::default();
        let problems = cfg.validate();
        assert!(problems.iter().any(|p| p.contains("embed.api_key")));
        assert!(problems.iter().any(|p| p.contains("sources")));
    }
}
