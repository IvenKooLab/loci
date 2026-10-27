//! BM25 tokenizers behind a registry, matching the Python implementation.
//!
//! `default` is frozen: latin/digit runs whole, CJK as single characters. An
//! install that never chose a tokenizer must keep the behaviour it had.
//! `cjk_bigram` indexes overlapping CJK bigrams so 检索 matches inside
//! 全文检索, while 定期检查索引 produces no 检索 bigram — precision without a
//! dictionary. `HyphenJoin` answers the latin half of the same problem.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum Tokenizer {
    #[default]
    Default,
    CjkBigram,
    HyphenJoin,
}

impl Tokenizer {
    pub fn from_name(name: &str) -> Option<Self> {
        match name {
            "default" | "" => Some(Self::Default),
            "cjk_bigram" => Some(Self::CjkBigram),
            "hyphen_join" => Some(Self::HyphenJoin),
            _ => None,
        }
    }

    pub fn names() -> &'static [&'static str] {
        &["default", "cjk_bigram", "hyphen_join"]
    }

    pub fn tokenize(self, text: &str) -> Vec<String> {
        match self {
            Self::Default => default_tokens(text),
            Self::HyphenJoin => hyphen_join_tokens(text),
            Self::CjkBigram => cjk_bigram_tokens(text),
        }
    }
}

fn is_cjk(c: char) -> bool {
    matches!(c, '\u{4e00}'..='\u{9fff}')
}

fn is_word_char(c: char) -> bool {
    c.is_ascii_alphanumeric()
}

/// Runs of ascii alphanumerics and single CJK characters, lowercased.
fn default_tokens(text: &str) -> Vec<String> {
    let lowered = text.to_lowercase();
    let mut out = Vec::new();
    let mut word = String::new();
    for c in lowered.chars() {
        if is_word_char(c) {
            word.push(c);
        } else {
            if !word.is_empty() {
                out.push(std::mem::take(&mut word));
            }
            if is_cjk(c) {
                out.push(c.to_string());
            }
        }
    }
    if !word.is_empty() {
        out.push(word);
    }
    out
}

/// default, plus the joined spelling of hyphenated compounds so a `wifi`
/// query finds `Wi-Fi`.
fn hyphen_join_tokens(text: &str) -> Vec<String> {
    let mut out = default_tokens(text);
    let lowered = text.to_lowercase();
    let chars: Vec<char> = lowered.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        if !is_word_char(chars[i]) {
            i += 1;
            continue;
        }
        let start = i;
        while i < chars.len() && is_word_char(chars[i]) {
            i += 1;
        }
        // a hyphenated chain: word - word (- word)*
        let mut parts = 1;
        let mut j = i;
        while j + 1 < chars.len() && chars[j] == '-' && is_word_char(chars[j + 1]) {
            parts += 1;
            j += 1;
            while j < chars.len() && is_word_char(chars[j]) {
                j += 1;
            }
        }
        if parts > 1 {
            let joined: String = chars[start..j].iter().filter(|c| **c != '-').collect();
            if !joined.is_empty() {
                out.push(joined);
            }
            i = j;
        }
    }
    out
}

/// Overlapping CJK bigrams; a one-character run stays a single token.
fn cjk_bigram_tokens(text: &str) -> Vec<String> {
    let lowered = text.to_lowercase();
    let mut out = Vec::new();
    let mut latin = String::new();
    let mut cjk_run: Vec<char> = Vec::new();

    let flush_latin = |latin: &mut String, out: &mut Vec<String>| {
        if !latin.is_empty() {
            out.push(std::mem::take(latin));
        }
    };
    let flush_cjk = |run: &mut Vec<char>, out: &mut Vec<String>| {
        match run.len() {
            0 => {}
            1 => out.push(run[0].to_string()),
            _ => {
                for w in run.windows(2) {
                    out.push(w.iter().collect());
                }
            }
        }
        run.clear();
    };

    for c in lowered.chars() {
        if is_cjk(c) {
            flush_latin(&mut latin, &mut out);
            cjk_run.push(c);
        } else if is_word_char(c) || c == '-' {
            flush_cjk(&mut cjk_run, &mut out);
            latin.push(c);
        } else {
            flush_latin(&mut latin, &mut out);
            flush_cjk(&mut cjk_run, &mut out);
        }
    }
    flush_latin(&mut latin, &mut out);
    flush_cjk(&mut cjk_run, &mut out);
    // latin runs above keep hyphens; add the joined spelling of compounds so
    // this tokenizer agrees with hyphen_join on the latin half
    for tok in hyphen_join_tokens(&lowered) {
        if !tok.contains('-') && !tok.chars().any(is_cjk) && !out.contains(&tok) {
            out.push(tok);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_splits_cjk_into_single_chars() {
        assert_eq!(Tokenizer::Default.tokenize("向量检索"),
                   ["向", "量", "检", "索"]);
    }

    #[test]
    fn default_keeps_latin_words_whole() {
        assert_eq!(Tokenizer::Default.tokenize("RAG embedding"),
                   ["rag", "embedding"]);
    }

    #[test]
    fn default_does_not_join_hyphenates() {
        let toks = Tokenizer::Default.tokenize("Wi-Fi reconnect");
        assert_eq!(toks, ["wi", "fi", "reconnect"]);
        assert!(!toks.iter().any(|t| t == "wifi"));
    }

    #[test]
    fn hyphen_join_adds_the_joined_form() {
        let toks = Tokenizer::HyphenJoin.tokenize("Wi-Fi reconnect");
        assert!(toks.iter().any(|t| t == "wifi"), "{toks:?}");
        assert!(toks.iter().any(|t| t == "wi"));
    }

    #[test]
    fn hyphen_join_handles_multi_part_compounds() {
        assert!(Tokenizer::HyphenJoin.tokenize("state-of-the-art")
            .iter().any(|t| t == "stateoftheart"));
    }

    #[test]
    fn bigram_keeps_phrase_inside_a_longer_word() {
        assert_eq!(Tokenizer::CjkBigram.tokenize("全文检索"),
                   ["全文", "文检", "检索"]);
    }

    #[test]
    fn bigram_does_not_join_across_word_boundaries() {
        let toks = Tokenizer::CjkBigram.tokenize("定期检查索引");
        assert!(!toks.iter().any(|t| t == "检索"), "{toks:?}");
    }

    #[test]
    fn bigram_single_char_run_stays_one_token() {
        assert_eq!(Tokenizer::CjkBigram.tokenize("检"), ["检"]);
    }

    #[test]
    fn registry_lookup() {
        assert_eq!(Tokenizer::from_name("cjk_bigram"), Some(Tokenizer::CjkBigram));
        assert_eq!(Tokenizer::from_name(""), Some(Tokenizer::Default));
        assert_eq!(Tokenizer::from_name("nope"), None);
    }
}
