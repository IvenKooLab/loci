//! Default harness logos, embedded in the binary.
//!
//! Logos are application assets (Ekko's `coding-agents/` convention): a fresh
//! instance must render them with no files to copy. A user's `icons/` dir
//! still wins — drop a file with the same name there to override the builtin.

/// `(filename, bytes)` for every builtin logo.
pub static EMBEDDED_ICONS: &[(&str, &[u8])] = &[
    ("zcode-logo.png", include_bytes!("../../../../icons/zcode-logo.png")),
    ("codex-openai.png", include_bytes!("../../../../icons/codex-openai.png")),
    ("claude-code.svg", include_bytes!("../../../../icons/claude-code.svg")),
    ("deepseek.svg", include_bytes!("../../../../icons/deepseek.svg")),
    ("cursor-logo.png", include_bytes!("../../../../icons/cursor-logo.png")),
    ("copilot-logo.svg", include_bytes!("../../../../icons/copilot-logo.svg")),
    ("qwen-logo.svg", include_bytes!("../../../../icons/qwen-logo.svg")),
    ("kimi-logo.png", include_bytes!("../../../../icons/kimi-logo.png")),
    ("qoder-logo.svg", include_bytes!("../../../../icons/qoder-logo.svg")),
];

/// The bytes of a builtin logo, when the name is one of ours.
pub fn embedded_icon(name: &str) -> Option<&'static [u8]> {
    EMBEDDED_ICONS
        .iter()
        .find(|(n, _)| *n == name)
        .map(|(_, bytes)| *bytes)
}

pub fn is_builtin_icon(name: &str) -> bool {
    EMBEDDED_ICONS.iter().any(|(n, _)| *n == name)
}
