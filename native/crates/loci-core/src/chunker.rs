//! Chunking: split markdown along headings, keep fenced code intact, fall back
//! to a sliding window for oversized prose. Every chunk carries a heading
//! breadcrumb so a citation points at a section, not just a file.
//!
//! Ported from the Python implementation with the same semantics: a heading
//! inside a fenced block is code, not a heading; a block that fits stays whole;
//! a tiny tail window is merged into its neighbour rather than dropped.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Chunk {
    pub text: String,
    pub section: String,
}

#[derive(Debug, Clone, Copy)]
pub struct ChunkParams {
    pub size: usize,
    pub overlap: usize,
}

impl Default for ChunkParams {
    fn default() -> Self {
        Self { size: 800, overlap: 100 }
    }
}

/// A heading snapshot becomes the breadcrumb: "Install > Prerequisites".
fn is_fence(line: &str) -> bool {
    line.trim_start().starts_with("```")
}

fn heading(line: &str) -> Option<(usize, String)> {
    let hashes = line.chars().take_while(|c| *c == '#').count();
    if !(1..=6).contains(&hashes) {
        return None;
    }
    let rest = &line[hashes..];
    if !rest.starts_with(' ') && !rest.starts_with('\t') {
        return None;
    }
    Some((hashes, rest.trim().to_string()))
}

/// (breadcrumb, block) pairs; each block keeps its heading line.
fn blocks_with_breadcrumbs(text: &str) -> Vec<(String, String)> {
    let mut out = Vec::new();
    let mut stack: Vec<(usize, String)> = Vec::new();
    let mut lines: Vec<&str> = Vec::new();
    let mut in_fence = false;

    let crumb = |stack: &Vec<(usize, String)>| -> String {
        let mut levels: Vec<usize> = stack.iter().map(|(l, _)| *l).collect();
        levels.sort_unstable();
        levels
            .iter()
            .filter_map(|lvl| stack.iter().find(|(l, _)| l == lvl).map(|(_, t)| t.clone()))
            .collect::<Vec<_>>()
            .join(" > ")
    };

    let flush = |lines: &mut Vec<&str>, out: &mut Vec<(String, String)>, crumb: &str| {
        if !lines.is_empty() {
            let joined = lines.join("\n");
            if !joined.trim().is_empty() {
                out.push((crumb.to_string(), joined));
            }
            lines.clear();
        }
    };

    for line in text.lines() {
        if is_fence(line) {
            in_fence = !in_fence;
            lines.push(line);
            continue;
        }
        match (!in_fence).then(|| heading(line)).flatten() {
            None => lines.push(line),
            Some((level, title)) => {
                flush(&mut lines, &mut out, &crumb(&stack));
                stack.retain(|(l, _)| *l < level);
                stack.push((level, title));
                lines.push(line);
            }
        }
    }
    flush(&mut lines, &mut out, &crumb(&stack));
    out
}

/// Split a block into (segment, is_code). An unclosed fence treats the rest of
/// the block as code, which is the safe default.
fn split_around_code(block: &str) -> Vec<(String, bool)> {
    let mut segments = Vec::new();
    let mut prose: Vec<&str> = Vec::new();
    let mut code: Vec<&str> = Vec::new();
    let mut in_code = false;

    for line in block.lines() {
        if is_fence(line) {
            if in_code {
                code.push(line);
                segments.push((code.join("\n"), true));
                code.clear();
                in_code = false;
            } else {
                if !prose.join("\n").trim().is_empty() {
                    segments.push((prose.join("\n"), false));
                }
                prose.clear();
                in_code = true;
                code.push(line);
            }
        } else if in_code {
            code.push(line);
        } else {
            prose.push(line);
        }
    }
    if in_code {
        segments.push((code.join("\n"), true));
    } else if !prose.join("\n").trim().is_empty() {
        segments.push((prose.join("\n"), false));
    }
    segments
}

fn sliding_window(text: &str, size: usize, overlap: usize) -> Vec<String> {
    let step = size.saturating_sub(overlap).max(1);
    let chars: Vec<char> = text.chars().collect();
    let mut out = Vec::new();
    let mut i = 0;
    while i < chars.len() {
        let end = (i + size).min(chars.len());
        out.push(chars[i..end].iter().collect());
        i += step;
    }
    out
}

pub fn split_markdown(text: &str, params: ChunkParams) -> Vec<Chunk> {
    let ChunkParams { size, overlap } = params;
    let mut out: Vec<Chunk> = Vec::new();

    for (crumb, block) in blocks_with_breadcrumbs(text) {
        let block = block.trim().to_string();
        if block.is_empty() {
            continue;
        }
        if block.chars().count() <= size {
            out.push(Chunk { text: block, section: crumb });
            continue;
        }
        for (seg, is_code) in split_around_code(&block) {
            let seg = seg.trim().to_string();
            if seg.is_empty() {
                continue;
            }
            if is_code || seg.chars().count() <= size {
                out.push(Chunk { text: seg, section: crumb.clone() });
            } else {
                let mut pieces = sliding_window(&seg, size, overlap);
                if pieces.len() > 1 && pieces.last().map(|p| p.chars().count()).unwrap_or(0) < 30 {
                    if let Some(tail) = pieces.pop() {
                        if let Some(last) = pieces.last_mut() {
                            last.push_str(&tail);
                        }
                    }
                }
                out.extend(pieces.into_iter().map(|text| Chunk {
                    text,
                    section: crumb.clone(),
                }));
            }
        }
    }
    out.retain(|c| !c.text.trim().is_empty());
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn breadcrumbs_nest_by_level() {
        let md = "# Top\n\nintro\n\n## Sub\n\nbody\n";
        let chunks = split_markdown(md, ChunkParams::default());
        let sections: Vec<&str> = chunks.iter().map(|c| c.section.as_str()).collect();
        assert!(sections.contains(&"Top"));
        assert!(sections.contains(&"Top > Sub"));
    }

    #[test]
    fn heading_inside_fence_is_code() {
        let md = "# Real\n\n```\n# not a heading\n```\n";
        let chunks = split_markdown(md, ChunkParams::default());
        assert!(chunks.iter().all(|c| c.section == "Real"));
    }

    #[test]
    fn short_blocks_survive_whole() {
        let chunks = split_markdown("# A\n\ntiny", ChunkParams::default());
        assert!(chunks.iter().any(|c| c.text.contains("tiny")));
    }

    #[test]
    fn long_prose_is_windowed_and_tiny_tail_merged() {
        let body = "x".repeat(250);
        let chunks = split_markdown(
            &body,
            ChunkParams { size: 100, overlap: 10 },
        );
        assert!(chunks.len() >= 3);
        assert!(chunks.iter().all(|c| c.text.chars().count() <= 110));
    }

    #[test]
    fn code_fence_is_never_cut_mid_block() {
        let code = format!("```\n{}\n```", "y".repeat(300));
        let md = format!("# A\n\n{code}\n");
        let chunks = split_markdown(&md, ChunkParams { size: 50, overlap: 5 });
        assert!(chunks.iter().any(|c| c.text.contains("yyy") && c.text.starts_with("```")));
    }

    #[test]
    fn empty_input_yields_nothing() {
        assert!(split_markdown("", ChunkParams::default()).is_empty());
        assert!(split_markdown("   \n\n  ", ChunkParams::default()).is_empty());
    }
}
