//! Harness memory hub: find the memory directories of AI coding tools.
//!
//! A harness shows up when its *probe* hits (an install home, an app bundle, an
//! env var); its memory roots are then scanned for real markdown. Nothing is
//! invented on disk, and a tool that is not installed is simply absent from the
//! list rather than showing up empty.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use serde::Serialize;

use crate::config::HarnessEntry;
use crate::loader::{file_hash, load_one};

#[derive(Debug, Clone, Serialize)]
pub struct Harness {
    pub name: String,
    pub display: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub icon: String,
    pub roots: Vec<String>,
    /// True when this came from config rather than the built-in registry.
    pub configured: bool,
}

/// Scan preset per harness kind. `generic` is recursive, `codex` is defined as
/// top level only, `zcode` looks in its projects layout first.
fn type_globs(kind: &str) -> &'static [&'static str] {
    match kind {
        "zcode" => &["projects/*/memory/*.md"],
        "codex" => &["*.md"],
        _ => &["**/*.md"],
    }
}

/// Kinds that fall back to a recursive scan when their own pattern matches
/// nothing. `zcode` is the reason: memories usually live under
/// `projects/*/memory/`, but an installation that never created that layout
/// still has notes somewhere under its root, and dropping them silently is
/// worse than being generous. `codex` is deliberately absent — its flatness is
/// the contract.
fn has_recursive_fallback(kind: &str) -> bool {
    kind == "zcode"
}

fn is_glob(text: &str) -> bool {
    text.chars().any(|c| matches!(c, '*' | '?' | '['))
}

/// Expand `~` and a leading `$VAR`; `None` when the variable is unset.
fn expand(spec: &str) -> Option<String> {
    let spec = spec.trim();
    if let Some(rest) = spec.strip_prefix('$') {
        let (var, tail) = match rest.split_once('/') {
            Some((v, t)) => (v, t),
            None => (rest, ""),
        };
        let value = std::env::var(var).ok()?;
        if value.trim().is_empty() {
            return None;
        }
        let mut s = value;
        if !tail.is_empty() {
            s.push('/');
            s.push_str(tail);
        }
        return Some(expand_tilde(&s));
    }
    Some(expand_tilde(spec))
}

fn expand_tilde(spec: &str) -> String {
    if let Some(rest) = spec.strip_prefix("~/") {
        if let Ok(home) = std::env::var("HOME") {
            return format!("{home}/{rest}");
        }
    }
    spec.to_string()
}

/// The non-wildcard part of a root, for "is this chunk under that harness?".
/// For `~/.claude/**/*.md` that is `~/.claude`.
pub fn root_prefix(root: &str) -> String {
    if !is_glob(root) {
        return root.to_string();
    }
    let cut = root
        .char_indices()
        .find(|(_, c)| matches!(c, '*' | '?' | '['))
        .map(|(i, _)| i)
        .unwrap_or(root.len());
    let head = &root[..cut];
    match head.rfind('/') {
        Some(i) if i > 0 => head[..i].to_string(),
        _ => head.to_string(),
    }
}

struct Spec {
    name: &'static str,
    display: &'static str,
    kind: &'static str,
    emoji: &'static str,
    icons: &'static [&'static str],
    probe: &'static [&'static str],
    memory: &'static [&'static str],
}

/// Built-in registry: what we know about each tool before this machine is
/// inspected. A `[[harness]]` entry overrides or adds to it by name.
const KNOWN: &[Spec] = &[
    Spec {
        name: "zcode",
        display: "ZCode",
        kind: "zcode",
        emoji: "⚡",
        icons: &["zcode-logo.png", "zcode.png"],
        probe: &["~/.zcode"],
        memory: &["~/.zcode/cli/memories"],
    },
    Spec {
        name: "codex",
        display: "Codex",
        kind: "codex",
        emoji: "🐙",
        icons: &["codex-openai.png", "codex.png"],
        probe: &["~/.codex"],
        memory: &["~/.codex/memories"],
    },
    Spec {
        name: "dsh",
        display: "DeepSeek Harness",
        kind: "generic",
        emoji: "🐳",
        icons: &["deepseek.svg", "deepseek.png", "dsh.png"],
        probe: &[
            "$DSH_HOME",
            "/Applications/DeepSeek Harness.app",
            "~/Applications/DeepSeek Harness.app",
        ],
        memory: &["$DSH_HOME"],
    },
    Spec {
        name: "claude",
        display: "Claude Code",
        kind: "codex",
        emoji: "🧠",
        icons: &["claude-code.svg", "claude.png"],
        probe: &["~/.claude"],
        memory: &["~/.claude/memories", "~/.claude/CLAUDE.md"],
    },
];

fn icon_for(spec: &Spec, icons_dir: &Path) -> String {
    for candidate in spec.icons {
        if icons_dir.join(candidate).is_file() {
            return (*candidate).to_string();
        }
    }
    spec.emoji.to_string()
}

/// Registry probe plus per-machine detection, then `[[harness]]` overrides.
/// Resolve the icon directory the way every front-end should: relative paths
/// are relative to the instance (the directory holding the store), because that
/// is where `loci` puts `icons/` and where a user expects to find them.
pub fn icons_dir(config: &crate::config::Config) -> std::path::PathBuf {
    let configured = config.http.icons.trim();
    if configured.is_empty() {
        return std::path::Path::new(&config.store.path)
            .parent()
            .unwrap_or(Path::new("."))
            .join("icons");
    }
    let p = std::path::PathBuf::from(configured);
    if p.is_absolute() {
        p
    } else {
        std::path::Path::new(&config.store.path)
            .parent()
            .unwrap_or(Path::new("."))
            .join(p)
    }
}

pub fn load(config: &crate::config::Config) -> Vec<Harness> {
    load_with_icons(config, &icons_dir(config))
}

/// Same, with an explicit icons directory. The console resolves `[http] icons`
/// against its corpus root, so `./icons` means "beside the notes", not "beside
/// whatever directory the process was started from".
pub fn load_with_icons(config: &crate::config::Config, icons_dir: &Path) -> Vec<Harness> {
    let icons_dir = if icons_dir.as_os_str().is_empty() {
        PathBuf::from("./icons")
    } else {
        icons_dir.to_path_buf()
    };
    let mut out: Vec<Harness> = Vec::new();

    for spec in KNOWN {
        let installed = spec
            .probe
            .iter()
            .filter_map(|p| expand(p))
            .any(|p| Path::new(&p).exists());
        if !installed {
            continue;                     // not on this machine: absent, not empty
        }
        let roots: Vec<String> = spec
            .memory
            .iter()
            .filter_map(|p| expand(p))
            .collect();
        out.push(Harness {
            name: spec.name.to_string(),
            display: spec.display.to_string(),
            kind: spec.kind.to_string(),
            icon: icon_for(spec, &icons_dir),
            roots,
            configured: false,
        });
    }

    for entry in &config.harness {
        merge_entry(&mut out, entry);
    }
    out
}

fn merge_entry(out: &mut Vec<Harness>, entry: &HarnessEntry) {
    let name = entry.name.trim();
    if name.is_empty() {
        return;
    }
    let kind = {
        let k = entry.r#type.trim().to_lowercase();
        if k.is_empty() { "generic".to_string() } else { k }
    };
    let roots: Vec<String> = entry.paths.iter().filter_map(|p| expand(p)).collect();
    match out.iter_mut().find(|h| h.name == name) {
        Some(existing) => {
            if !entry.display.trim().is_empty() {
                existing.display = entry.display.trim().to_string();
            }
            existing.kind = kind;
            if !roots.is_empty() {
                existing.roots = roots;
            }
            existing.configured = true;
        }
        None => out.push(Harness {
            name: name.to_string(),
            display: if entry.display.trim().is_empty() {
                name.to_string()
            } else {
                entry.display.trim().to_string()
            },
            kind,
            icon: "🗂️".to_string(),
            roots,
            configured: true,
        }),
    }
}

/// Markdown files under one root, per its kind.
///
/// The fallback decision is per root, not per harness: Claude declares
/// `~/.claude/memories` plus a single `CLAUDE.md`, and a harness-wide check
/// would drag deep subdirectories into a preset that means top-level only.
fn scan_root(root: &Path, kind: &str) -> BTreeSet<PathBuf> {
    let mut found = BTreeSet::new();
    if !root.exists() {
        return found;
    }
    if root.is_file() {
        if root.extension().and_then(|e| e.to_str()).map(|e| e.eq_ignore_ascii_case("md")) == Some(true) {
            found.insert(root.to_path_buf());
        }
        return found;
    }
    for pattern in type_globs(kind) {
        let hits = glob_files(root, pattern);
        if !hits.is_empty() {
            return hits;
        }
    }
    if has_recursive_fallback(kind) {
        return glob_files(root, "**/*.md");
    }
    found
}

/// Minimal glob: `*`, `**` and literal path segments. Enough for the presets
/// and for `paths = ["~/vault/**/*.md"]`, without pulling in a dependency.
pub fn glob_files(base: &Path, pattern: &str) -> BTreeSet<PathBuf> {
    let mut out = BTreeSet::new();
    let parts: Vec<&str> = pattern.split('/').collect();
    walk(base, &parts, &mut out);
    out
}

fn walk(dir: &Path, parts: &[&str], out: &mut BTreeSet<PathBuf>) {
    let Some((head, rest)) = parts.split_first() else { return };
    if *head == "**" {
        // zero directories, then one level deeper (recursively)
        walk(dir, rest, out);
        if let Ok(entries) = std::fs::read_dir(dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    walk(&path, parts, out);
                }
            }
        }
        return;
    }
    if head.contains('*') {
        // split "pre*suf"; `*.md` gives ("", ".md"), so both empty is a
        // wildcard for everything — check that case explicitly
        let (prefix, suffix) = match head.split_once('*') {
            Some((pre, suf)) => (pre, suf),
            None => (*head, ""),
        };
        if let Ok(entries) = std::fs::read_dir(dir) {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                if !name.starts_with(prefix) || !name.ends_with(suffix) {
                    continue;
                }
                let path = entry.path();
                if rest.is_empty() {
                    if path.is_file() {
                        out.insert(path);
                    }
                } else if path.is_dir() {
                    walk(&path, rest, out);
                }
            }
        }
        return;
    }
    let next = dir.join(head);
    if rest.is_empty() {
        if next.is_file() {
            out.insert(next);
        }
    } else {
        walk(&next, rest, out);
    }
}

/// Every markdown file this harness owns.
pub fn memory_files(h: &Harness) -> Vec<PathBuf> {
    let mut files: BTreeSet<PathBuf> = BTreeSet::new();
    for root in &h.roots {
        if is_glob(root) {
            // split "base" from the pattern so glob_files can walk it
            let cut = root
                .char_indices()
                .find(|(_, c)| matches!(c, '*' | '?' | '['))
                .map(|(i, _)| i)
                .unwrap_or(root.len());
            let head = &root[..cut];
            let base = match head.rfind('/') {
                Some(i) => &head[..i],
                None => ".",
            };
            let pattern = &root[base.len()..].trim_start_matches('/');
            for p in glob_files(Path::new(base), pattern) {
                if p.is_file() {
                    files.insert(p);
                }
            }
            continue;
        }
        files.extend(scan_root(Path::new(root), &h.kind));
    }
    files.into_iter().collect()
}

/// Content fingerprint over (file name, content hash), order-stable.
pub fn fingerprint(files: &[PathBuf]) -> String {
    // sort first: callers pass whatever order they collected in, and an
    // order-dependent digest would look "stale" after a directory read order
    // changed for reasons the user cannot see
    let mut sorted: Vec<&PathBuf> = files.iter().collect();
    sorted.sort();
    let mut lines = Vec::new();
    for p in sorted {
        let digest = std::fs::read(p)
            .map(|bytes| {
                use sha1::{Digest, Sha1};
                let mut h = Sha1::new();
                h.update(&bytes);
                format!("{:x}", h.finalize())
            })
            .unwrap_or_else(|_| "unreadable".to_string());
        lines.push(format!(
            "{}:{digest}",
            p.file_name().map(|s| s.to_string_lossy()).unwrap_or_default()
        ));
    }
    file_hash(&lines.join("\n"))[..16].to_string()
}

#[derive(Debug, Clone, Serialize)]
pub struct HarnessStats {
    pub name: String,
    pub display: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub icon: String,
    pub files: usize,
    pub chars: u64,
    pub chunks: usize,
    pub last_updated: String,
    pub summary: Summary,
    /// Directories that vanished: the tool is configured but not installed here.
    pub missing_roots: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct Summary {
    pub path: String,
    pub status: String,
}

/// Per-harness stats: file count, size, last update, indexed chunks, and
/// whether its digest note is stale. Zero LLM cost — this is what the console
/// renders and what `brain_harness` returns.
pub fn stats(
    config: &crate::config::Config,
    store: &crate::store::Store,
    harnesses: &[Harness],
) -> Vec<HarnessStats> {
    let per_source = store.per_source().unwrap_or_default();
    let mut out = Vec::new();
    for h in harnesses {
        let files = memory_files(h);
        let prefixes: Vec<String> = h.roots.iter().map(|r| root_prefix(r)).collect();
        let chunks = per_source
            .iter()
            .filter(|(src, _)| prefixes.iter().any(|p| src.starts_with(p)))
            .map(|(_, n)| *n)
            .sum();
        let mut chars = 0u64;
        let mut last: Option<f64> = None;
        for f in &files {
            if let Ok(meta) = std::fs::metadata(f) {
                chars += meta.len();
                if let Ok(modified) = meta.modified() {
                    let secs = modified
                        .duration_since(std::time::UNIX_EPOCH)
                        .map(|d| d.as_secs_f64())
                        .unwrap_or(0.0);
                    last = Some(last.map_or(secs, |l: f64| l.max(secs)));
                }
            }
        }
        let missing = h.roots.iter().filter(|r| !Path::new(r).exists()).count();
        let summary_path = summary_file(config, &h.name);
        let stored = stored_fingerprint(&summary_path);
        let current = fingerprint(&files);
        let status = match stored {
            Some(s) if s == current => "fresh",
            Some(_) => "stale",
            None => "missing",
        };
        out.push(HarnessStats {
            name: h.name.clone(),
            display: h.display.clone(),
            kind: h.kind.clone(),
            icon: h.icon.clone(),
            files: files.len(),
            chars,
            chunks,
            last_updated: last.map(format_time).unwrap_or_default(),
            summary: Summary {
                path: summary_path.display().to_string(),
                status: status.to_string(),
            },
            missing_roots: missing,
        });
    }
    out
}

fn summary_file(config: &crate::config::Config, name: &str) -> PathBuf {
    PathBuf::from(&config.store.path)
        .parent()
        .unwrap_or(Path::new("."))
        .join("memories")
        .join("harness")
        .join(format!("{}.md", slug(name)))
}

fn slug(text: &str) -> String {
    text.to_lowercase()
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect::<String>()
        .split('-')
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join("-")
}

fn stored_fingerprint(path: &Path) -> Option<String> {
    let text = std::fs::read_to_string(path).ok()?;
    text.lines()
        .find_map(|l| l.strip_prefix("fingerprint:").map(|v| v.trim().to_string()))
}

fn format_time(secs: f64) -> String {
    // HH:MM from an epoch-seconds value; the console shows the date separately
    let total = secs as u64;
    format!("{:04}-{:02}-{:02} {:02}:{:02}",
        1970 + total / 31_536_000,
        (total / 2_592_000) % 12 + 1,
        (total / 86_400) % 30 + 1,
        (total / 3600) % 24,
        (total / 60) % 60)
}

/// A harness's memory files loaded as documents, ready to index.
pub fn documents(h: &Harness) -> Vec<crate::loader::Document> {
    memory_files(h)
        .iter()
        .filter_map(|p| load_one(p).ok().flatten())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmpdir(tag: &str) -> PathBuf {
        use std::sync::atomic::{AtomicU64, Ordering};
        static SEQ: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "loci-harness-{tag}-{}-{}",
            std::process::id(),
            SEQ.fetch_add(1, Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write(path: &Path, body: &str) {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).unwrap();
        }
        std::fs::write(path, body).unwrap();
    }

    fn harness(name: &str, kind: &str, roots: Vec<&str>) -> Harness {
        Harness {
            name: name.into(),
            display: name.into(),
            kind: kind.into(),
            icon: "x".into(),
            roots: roots.into_iter().map(str::to_string).collect(),
            configured: true,
        }
    }

    #[test]
    fn codex_preset_is_flat() {
        let dir = tmpdir("codex");
        write(&dir.join("MEMORY.md"), "i");
        write(&dir.join("note.md"), "n");
        write(&dir.join("sub/deep.md"), "d");
        let h = harness("codex", "codex", vec![dir.to_str().unwrap()]);
        let names: Vec<String> = memory_files(&h)
            .iter()
            .map(|p| p.file_name().unwrap().to_string_lossy().to_string())
            .collect();
        assert_eq!(names, vec!["MEMORY.md", "note.md"]);
    }

    #[test]
    fn zcode_falls_back_to_recursive_when_projects_layout_is_absent() {
        let dir = tmpdir("zcode");
        write(&dir.join("a/b/c.md"), "deep");
        let h = harness("z", "zcode", vec![dir.to_str().unwrap()]);
        assert_eq!(memory_files(&h).len(), 1);
    }

    #[test]
    fn generic_is_recursive() {
        let dir = tmpdir("generic");
        write(&dir.join("x/y/z.md"), "deep");
        let h = harness("g", "generic", vec![dir.to_str().unwrap()]);
        assert_eq!(memory_files(&h).len(), 1);
    }

    #[test]
    fn fallback_is_per_root_not_per_harness() {
        // Claude: an empty memories dir plus a single CLAUDE.md at the root
        let dir = tmpdir("claude");
        let memories = dir.join("memories");
        std::fs::create_dir_all(&memories).unwrap();
        write(&memories.join("sub/deep.md"), "should not leak");
        write(&dir.join("CLAUDE.md"), "# top");
        let h = harness(
            "claude",
            "codex",
            vec![memories.to_str().unwrap(), dir.join("CLAUDE.md").to_str().unwrap()],
        );
        let names: Vec<String> = memory_files(&h)
            .iter()
            .map(|p| p.file_name().unwrap().to_string_lossy().to_string())
            .collect();
        assert!(names.contains(&"CLAUDE.md".to_string()));
        assert!(!names.contains(&"deep.md".to_string()), "{names:?}");
    }

    #[test]
    fn glob_root_needs_no_code_change() {
        let dir = tmpdir("glob");
        write(&dir.join("projects/one.md"), "x");
        write(&dir.join("top.md"), "x");
        write(&dir.join("skip.txt"), "x");
        let pattern = format!("{}/**/*.md", dir.display());
        let h = harness("real", "generic", vec![&pattern]);
        let names: Vec<String> = memory_files(&h)
            .iter()
            .map(|p| p.file_name().unwrap().to_string_lossy().to_string())
            .collect();
        assert_eq!(names, vec!["one.md", "top.md"]);
    }

    #[test]
    fn root_prefix_strips_the_wildcard() {
        assert_eq!(root_prefix("/v/**/*.md"), "/v");
        assert_eq!(root_prefix("/plain"), "/plain");
    }

    #[test]
    fn fingerprint_changes_with_content() {
        let dir = tmpdir("fp");
        let f = dir.join("a.md");
        write(&f, "one");
        let first = fingerprint(std::slice::from_ref(&f));
        write(&f, "two");
        assert_ne!(first, fingerprint(&[f]));
    }

    #[test]
    fn fingerprint_is_order_stable() {
        let dir = tmpdir("fp2");
        let a = dir.join("a.md");
        let b = dir.join("b.md");
        write(&a, "a");
        write(&b, "b");
        assert_eq!(fingerprint(&[a.clone(), b.clone()]), fingerprint(&[b, a]));
    }

    #[test]
    fn config_entry_overrides_the_registry() {
        let mut config = crate::config::Config::default();
        config.harness.push(HarnessEntry {
            name: "zcode".into(),
            r#type: "generic".into(),
            paths: vec!["/custom/place".into()],
            display: "My ZCode".into(),
        });
        let list = load(&config);
        let z = list.iter().find(|h| h.name == "zcode").unwrap();
        assert_eq!(z.display, "My ZCode");
        assert_eq!(z.kind, "generic");
        assert_eq!(z.roots, vec!["/custom/place"]);
        assert!(z.configured);
    }

    #[test]
    fn a_new_harness_can_be_added_by_config_alone() {
        let mut config = crate::config::Config::default();
        config.harness.push(HarnessEntry {
            name: "my-tool".into(),
            r#type: "generic".into(),
            paths: vec!["/nowhere".into()],
            display: String::new(),
        });
        let list = load(&config);
        let added = list.iter().find(|h| h.name == "my-tool").unwrap();
        assert_eq!(added.display, "my-tool");
        assert_eq!(added.icon, "🗂️");
    }
}

#[cfg(test)]
mod icon_tests {
    use super::*;

    fn cfg_with_store(dir: &Path) -> crate::config::Config {
        let mut cfg = crate::config::Config::default();
        cfg.store.path = dir.join("index.db").to_string_lossy().to_string();
        cfg
    }

    #[test]
    fn icons_dir_defaults_to_the_instance() {
        let dir = std::env::temp_dir().join("loci-icons-default");
        let cfg = cfg_with_store(&dir);
        assert_eq!(icons_dir(&cfg), dir.join("icons"));
    }

    #[test]
    fn icons_dir_honours_a_relative_override() {
        let dir = std::env::temp_dir().join("loci-icons-rel");
        let mut cfg = cfg_with_store(&dir);
        cfg.http.icons = "brand".into();
        assert_eq!(icons_dir(&cfg), dir.join("brand"));
    }

    #[test]
    fn icons_dir_honours_an_absolute_override() {
        let mut cfg = crate::config::Config::default();
        cfg.http.icons = "/tmp/brand-assets".into();
        assert_eq!(icons_dir(&cfg), Path::new("/tmp/brand-assets"));
    }

    #[test]
    fn a_logo_on_disk_beats_the_emoji() {
        let dir = std::env::temp_dir().join("loci-icons-logo");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("icons")).unwrap();
        std::fs::write(dir.join("icons/codex-openai.png"), b"\x89PNG").unwrap();
        let cfg = cfg_with_store(&dir);
        let list = load(&cfg);
        // only meaningful when codex is actually installed on this machine
        if let Some(codex) = list.iter().find(|h| h.name == "codex") {
            assert_eq!(codex.icon, "codex-openai.png");
        }
    }
}
