//! Document loading and frontmatter, mirroring the Python behaviour that
//! matters for retrieval: YAML-ish `tags`/`aliases` are peeled off the body so
//! they do not pollute the text, and `[[wikilinks]]` are collected for the
//! link graph.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use sha2::{Digest, Sha256};
use walkdir::WalkDir;

#[derive(Debug, Clone)]
pub struct Document {
    pub path: PathBuf,
    pub body: String,
    pub tags: String,
    pub links: Vec<String>,
    pub hash: String,
    pub mtime: f64,
}

pub fn file_hash(text: &str) -> String {
    let mut h = Sha256::new();
    h.update(text.as_bytes());
    format!("{:x}", h.finalize())[..32].to_string()
}

pub fn chunk_hash(text: &str) -> String {
    let mut h = Sha256::new();
    h.update(text.as_bytes());
    format!("{:x}", h.finalize())[..16].to_string()
}

/// Split leading `---` frontmatter from the body. Only the flat subset the
/// project documents is honoured (scalars and `[a, b]` lists).
pub fn parse_frontmatter(text: &str) -> (String, String) {
    let mut lines = text.lines();
    match lines.next() {
        Some(first) if first.trim() == "---" => {}
        _ => return (String::new(), text.to_string()),
    }
    let mut meta_lines = Vec::new();
    let mut body_start = None;
    let mut consumed = 1usize; // the opening fence
    for line in text.lines().skip(1) {
        consumed += 1;
        if line.trim() == "---" {
            body_start = Some(consumed);
            break;
        }
        meta_lines.push(line);
    }
    let Some(start) = body_start else {
        return (String::new(), text.to_string());
    };
    let body: String = text
        .lines()
        .skip(start)
        .collect::<Vec<_>>()
        .join("\n");
    (meta_lines.join("\n"), body)
}

/// `tags: [a, b]` or `tags: a, b` -> "a,b".
pub fn tags_of(frontmatter: &str) -> String {
    for line in frontmatter.lines() {
        let Some((key, value)) = line.split_once(':') else { continue };
        if key.trim() != "tags" {
            continue;
        }
        let value = value.trim();
        let inner = value
            .strip_prefix('[')
            .and_then(|v| v.strip_suffix(']'))
            .unwrap_or(value);
        let tags: Vec<String> = inner
            .split(',')
            .map(|t| t.trim().trim_matches(|c| c == '"' || c == '\'').to_string())
            .filter(|t| !t.is_empty())
            .collect();
        return tags.join(",");
    }
    String::new()
}

/// `[[target]]` and `[[target|alias]]` -> target.
pub fn extract_wikilinks(body: &str) -> Vec<String> {
    let mut out = Vec::new();
    let bytes = body.as_bytes();
    let mut i = 0;
    while i + 1 < bytes.len() {
        if bytes[i] == b'[' && bytes[i + 1] == b'[' {
            if let Some(end) = body[i + 2..].find("]]") {
                let inner = &body[i + 2..i + 2 + end];
                let target = inner.split('|').next().unwrap_or("").split('#').next().unwrap_or("");
                let target = target.trim();
                if !target.is_empty() {
                    out.push(target.to_string());
                }
                i += 2 + end + 2;
                continue;
            }
        }
        i += 1;
    }
    out
}

fn read_text(path: &Path) -> Result<String> {
    std::fs::read_to_string(path).with_context(|| format!("read {path:?}"))
}

pub fn is_supported(path: &Path) -> bool {
    matches!(
        path.extension().and_then(|e| e.to_str()).map(|e| e.to_lowercase()),
        Some(ref e) if e == "md" || e == "markdown" || e == "txt" || e == "org" || e == "html" || e == "htm"
    )
}

pub fn load_one(path: &Path) -> Result<Option<Document>> {
    if !path.is_file() || !is_supported(path) {
        return Ok(None);
    }
    let raw = match read_text(path) {
        Ok(t) => t,
        Err(_) => return Ok(None), // not utf-8: skip rather than fail the scan
    };
    let (fm, body) = parse_frontmatter(&raw);
    if body.trim().is_empty() {
        return Ok(None);
    }
    let mtime = std::fs::metadata(path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);
    Ok(Some(Document {
        path: path.canonicalize().unwrap_or_else(|_| path.to_path_buf()),
        body,
        tags: tags_of(&fm),
        links: extract_wikilinks(&raw),
        hash: file_hash(&raw),
        mtime,
    }))
}

/// Every supported document under one root, sorted for deterministic indexing.
pub fn scan_root(root: &Path) -> Vec<Document> {
    let mut out = Vec::new();
    for entry in WalkDir::new(root).follow_links(false).into_iter().flatten() {
        if !entry.file_type().is_file() {
            continue;
        }
        if let Ok(Some(doc)) = load_one(entry.path()) {
            out.push(doc);
        }
    }
    out.sort_by(|a, b| a.path.cmp(&b.path));
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frontmatter_is_peeled_from_the_body() {
        let raw = "---\ntags: [a, b]\ntitle: T\n---\n\n# Heading\n\nbody";
        let (fm, body) = parse_frontmatter(raw);
        assert_eq!(tags_of(&fm), "a,b");
        assert!(!body.contains("tags:"));
        assert!(body.contains("# Heading"));
    }

    #[test]
    fn missing_frontmatter_leaves_text_untouched() {
        let raw = "# Heading\n\nbody";
        let (fm, body) = parse_frontmatter(raw);
        assert!(fm.is_empty());
        assert_eq!(body, raw);
    }

    #[test]
    fn unclosed_frontmatter_is_not_swallowed() {
        let raw = "---\ntags: [a]\n\nbody";
        let (fm, body) = parse_frontmatter(raw);
        assert!(fm.is_empty());
        assert_eq!(body, raw);
    }

    #[test]
    fn tags_accept_scalar_and_quoted_forms() {
        assert_eq!(tags_of("tags: aurora, hardware"), "aurora,hardware");
        assert_eq!(tags_of(r#"tags: ["x", 'y']"#), "x,y");
        assert_eq!(tags_of("title: nope"), "");
    }

    #[test]
    fn wikilinks_are_extracted() {
        let links = extract_wikilinks("see [[battery-budget]] and [[decisions|ADR]] x[[a#sec]]");
        assert_eq!(links, ["battery-budget", "decisions", "a"]);
    }

    #[test]
    fn load_one_reads_txt_and_skips_unsupported() {
        let dir = std::env::temp_dir().join(format!("loci-load-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let md = dir.join("a.md");
        std::fs::write(&md, "---\ntags: [t]\n---\n\nhello").unwrap();
        let doc = load_one(&md).unwrap().unwrap();
        assert_eq!(doc.tags, "t");
        assert!(doc.body.contains("hello"));

        let bin = dir.join("b.bin");
        std::fs::write(&bin, b"\x00\x01").unwrap();
        assert!(load_one(&bin).unwrap().is_none());
    }

    #[test]
    fn scan_root_is_sorted_and_recursive() {
        let dir = std::env::temp_dir().join(format!("loci-scan-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("sub")).unwrap();
        std::fs::write(dir.join("z.md"), "z").unwrap();
        std::fs::write(dir.join("sub/a.md"), "a").unwrap();
        let docs = scan_root(&dir);
        assert_eq!(docs.len(), 2);
        assert!(docs[0].path.ends_with("sub/a.md") || docs[0].path.ends_with("z.md"));
    }
}
