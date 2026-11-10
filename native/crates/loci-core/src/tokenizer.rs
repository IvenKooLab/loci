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
    Identifier,
}

impl Tokenizer {
    pub fn from_name(name: &str) -> Option<Self> {
        match name {
            "default" | "" => Some(Self::Default),
            "cjk_bigram" => Some(Self::CjkBigram),
            "hyphen_join" => Some(Self::HyphenJoin),
            "identifier" => Some(Self::Identifier),
            _ => None,
        }
    }

    pub fn names() -> &'static [&'static str] {
        &["default", "cjk_bigram", "hyphen_join", "identifier"]
    }

    pub fn tokenize(self, text: &str) -> Vec<String> {
        match self {
            Self::Default => default_tokens(text),
            Self::HyphenJoin => hyphen_join_tokens(text),
            Self::CjkBigram => cjk_bigram_tokens(text),
            Self::Identifier => identifier_tokens(text),
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
/// `default`, plus each identifier kept whole.
///
/// `default` splits on every non-alphanumeric run, so `user_id`, `user-id`
/// and `user id` all become `user` + `id`: identical tokens, mutually
/// indistinguishable, and a query for one ranks documents containing the
/// others equally. This appends the untouched surface form (lowercased) so
/// `user_id` also indexes as `user_id`.
///
/// Purely additive — every `default` token is still emitted, so recall cannot
/// drop; only identifier-bearing documents gain a discriminating term.
fn identifier_tokens(text: &str) -> Vec<String> {
    let mut out = default_tokens(text);
    let lowered = text.to_lowercase();
    let mut seen: std::collections::HashSet<String> = out.iter().cloned().collect();
    for run in identifier_runs(&lowered) {
        if seen.insert(run.clone()) {
            out.push(run);
        }
    }
    out
}

/// Identifier-shaped runs: segments joined by `_ - . : /`, or letters mixed
/// with digits (`sht45`, `x64`).
pub(crate) fn identifier_runs(lowered: &str) -> Vec<String> {
    let chars: Vec<char> = lowered.chars().collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        if !is_word_char(chars[i]) {
            i += 1;
            continue;
        }
        let start = i;
        while i < chars.len() {
            let c = chars[i];
            let joins = matches!(c, '_' | '-' | '.' | ':' | '/');
            if is_word_char(c) {
                i += 1;
            } else if joins
                && i + 1 < chars.len()
                && is_word_char(chars[i + 1])
                && i > start
            {
                i += 1;              // keep the separator inside the run
            } else {
                break;
            }
        }
        let run: String = chars[start..i].iter().collect();
        let trimmed = run.trim_matches(|c| matches!(c, '-' | '_' | '.' | ':' | '/'));
        let has_separator = trimmed.contains(['_', '-', '.', ':', '/']);
        let mixed = trimmed.chars().any(|c| c.is_ascii_digit())
            && trimmed.chars().any(|c| c.is_ascii_alphabetic());
        if !trimmed.is_empty() && (has_separator || mixed) {
            out.push(trimmed.to_string());
        }
    }
    out
}

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

    #[test]
    fn identifier_keeps_the_surface_form() {
        let toks = Tokenizer::Identifier.tokenize("call the user_id field");
        assert!(toks.contains(&"user_id".to_string()));
        // additive: the default tokens are still there
        assert!(toks.contains(&"user".to_string()));
        assert!(toks.contains(&"id".to_string()));
    }

    #[test]
    fn identifier_separates_underscore_from_hyphen() {
        let underscore = Tokenizer::Identifier.tokenize("user_id");
        let hyphen = Tokenizer::Identifier.tokenize("user-id");
        assert!(underscore.contains(&"user_id".to_string()));
        assert!(!underscore.contains(&"user-id".to_string()));
        assert!(hyphen.contains(&"user-id".to_string()));
        assert!(!hyphen.contains(&"user_id".to_string()));
    }

    #[test]
    fn identifier_does_not_double_plain_words() {
        // `sht45` is already one default token; re-emitting it would skew TF
        let toks = Tokenizer::Identifier.tokenize("SHT45 drift");
        assert_eq!(toks.iter().filter(|t| *t == "sht45").count(), 1);
    }

    #[test]
    fn identifier_is_registered_by_name() {
        assert_eq!(Tokenizer::from_name("identifier"), Some(Tokenizer::Identifier));
        assert!(Tokenizer::names().contains(&"identifier"));
    }

    #[test]
    fn default_stays_frozen() {
        assert_eq!(Tokenizer::Default.tokenize("user_id"),
                   vec!["user".to_string(), "id".to_string()]);
    }
}
