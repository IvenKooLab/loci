"""Harness memory hub: register AI coding tools (zcode, codex, ekko, ...) and
distill each one's native memory directory into a summary note that lives in
loci's own memory pool — so "what does every agent currently know" becomes one
searchable, chartable answer instead of a dozen scattered MEMORY.md files.

Two halves:
  stats      — pure filesystem + index bookkeeping, zero LLM cost
  summarize  — one LLM call per changed harness, fingerprint-gated (an
               unchanged harness costs nothing, so `watch` can call it freely)

Each harness is a [[harness]] entry in config.toml:
    [[harness]]
    name = "zcode"
    type = "zcode"                      # zcode | codex | generic
    paths = ["~/.zcode/cli/memories"]
    icon = "⚡"                          # emoji, or a file in the icons dir

`type` presets know where memories live:
  zcode   <root>/projects/*/memory/*.md      (+ fallback: recursive *.md)
  codex   <root>/*.md                        (+ fallback: recursive *.md)
  generic <root>/**/*.md
"""
from __future__ import annotations

import glob
import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

DEFAULT_ICONS = {"zcode": "⚡", "codex": "🐙", "claude": "🧠", "ekko": "🦜",
                 "dsh": "🐳", "cursor": "🖥️", "copilot": "🛩️", "kimi": "🌙"}

SUMMARY_PROMPT = (
    "You maintain the memory digest of one AI coding agent ('harness'). "
    "Given excerpts from its memory files, write a markdown digest with these "
    "sections: ## Scope (what this agent manages), ## Active projects, "
    "## Recent focus, ## Open items. Be concrete; mention memory file names "
    "when they matter. Reply in the dominant language of the excerpts. "
    "Under 400 words. Reply with ONLY the markdown body, no code fences."
)

# per-digest input caps: newest files first, ~700 chars each, 14k total
_PER_FILE_CHARS = 700
_TOTAL_CHARS = 14_000


@dataclass
class Harness:
    name: str
    type: str
    icon: str
    roots: list[Path] = field(default_factory=list)
    display: str = ""                        # pretty name; falls back to `name`


# Known harnesses, Ekko-style: a static registry (display name, type preset,
# icon candidates, probe paths) plus per-machine detection. A harness shows up
# when its probe hits (install home / app bundle / env var) — memory roots are
# then scanned for real markdown; nothing is invented on disk. [[harness]]
# config entries override or add to this registry by name.
KNOWN_HARNESSES = {
    "zcode": {
        "display": "ZCode", "type": "zcode", "emoji": "⚡",
        "icons": ["zcode-logo.png", "zcode.png"],
        "probe": ["~/.zcode"],
        "memory": ["~/.zcode/cli/memories"],
    },
    "codex": {
        "display": "Codex", "type": "codex", "emoji": "🐙",
        "icons": ["codex-openai.png", "codex.png"],
        "probe": ["~/.codex"],
        "memory": ["~/.codex/memories"],
    },
    "dsh": {
        "display": "DeepSeek Harness", "type": "generic", "emoji": "🐳",
        "icons": ["deepseek.svg", "deepseek.png", "dsh.png"],
        "probe": ["$DSH_HOME", "/Applications/DeepSeek Harness.app",
                  "~/Applications/DeepSeek Harness.app"],
        "memory": ["$DSH_HOME"],             # empty until DSH_HOME is set
    },
    "claude": {
        "display": "Claude Code", "type": "codex", "emoji": "🧠",
        "icons": ["claude-code.svg", "claude.png"],
        "probe": ["~/.claude"],
        "memory": ["~/.claude/memories", "~/.claude/CLAUDE.md"],
    },
}


def _expand(p: str) -> Path | None:
    """~-expansion plus $ENV prefixes; None when the env var is unset/empty."""
    if p.startswith("$"):
        v = os.environ.get(p[1:], "").strip()
        return Path(v).expanduser().resolve() if v else None
    return Path(p).expanduser().resolve()


def _icon_for(spec: dict, icons_dir: Path) -> str:
    """First icon candidate present in the instance icons dir, else emoji."""
    for f in spec.get("icons", []):
        if (icons_dir / f).is_file():
            return f
    return spec.get("emoji", "🗂️")


def load_harnesses(cfg) -> list[Harness]:
    icons_dir = Path(cfg.http.get("icons", "./icons")).expanduser()
    out: dict[str, Harness] = {}
    for name, spec in KNOWN_HARNESSES.items():          # registry + detection
        probes = [_expand(p) for p in spec.get("probe", [])]
        if not any(p and p.exists() for p in probes):
            continue
        roots = [r for r in (_expand(p) for p in spec.get("memory", []))
                 if r is not None]
        out[name] = Harness(name, spec["type"],
                            _icon_for(spec, icons_dir), roots,
                            display=spec.get("display", ""))
    for h in getattr(cfg, "harnesses", None) or []:     # config overrides/adds
        name = str(h.get("name", "")).strip()
        if not name:
            continue
        htype = str(h.get("type", "generic")).strip().lower() or "generic"
        icon = str(h.get("icon", "") or "").strip()
        raw = h.get("paths") or ([h["path"]] if h.get("path") else [])
        roots = [_root(str(p)) for p in raw if str(p).strip()]
        prev = out.get(name)
        out[name] = Harness(name, htype, icon or (prev.icon if prev else "🗂️"),
                            roots,
                            display=str(h.get("display", ""))
                            or (prev.display if prev else ""))
    return list(out.values())


# Markdown files each type preset looks for, relative to a root directory.
_TYPE_GLOBS = {
    "zcode": ["projects/*/memory/*.md"],
    "codex": ["*.md"],
    "generic": ["**/*.md"],
}


_GLOB_CHARS = set("*?[")


def _is_glob(text: str) -> bool:
    return any(ch in _GLOB_CHARS for ch in text)


def _root(spec: str) -> Path:
    """A configured root: resolved when it is a real path, left unexpanded when
    it is a glob (`resolve()` would normalise a wildcard into a literal)."""
    text = os.path.expandvars(spec.strip())
    p = Path(text).expanduser()
    return p if _is_glob(text) else p.resolve()


def _root_prefix(root: Path) -> str:
    """The non-wildcard part of a root, for "is this chunk under that harness?".
    For `~/.claude/**/*.md` that is `~/.claude`."""
    text = str(root)
    if not _is_glob(text):
        return text
    cut = min((text.index(ch) for ch in _GLOB_CHARS if ch in text), default=len(text))
    return os.path.dirname(text[:cut]) or text[:cut]


# Presets that fall back to a recursive scan when their own pattern matches
# nothing. `zcode` is the reason this exists: memories normally live under
# projects/*/memory/, but an installation that never created that layout still
# has real notes somewhere under its root, and dropping them silently is worse
# than being generous. `codex`/`generic` do not need it (`generic` is already
# recursive; `codex` is *defined* as top-level only, so its flatness is a
# contract, not an accident).
_RECURSIVE_FALLBACK = {"zcode"}


def _scan_root(root: Path, htype: str) -> set[Path]:
    """Markdown files under ONE root, per its preset.

    The fallback decision is per root, not per harness: a harness with several
    roots (Claude is `~/.claude/memories` plus a single `CLAUDE.md`) used to
    fall back as soon as the harness as a whole had produced no files, which
    dragged deep subdirectory content into a preset that means top-level only.
    """
    if not root.exists():
        return set()
    if root.is_file():
        return {root} if root.suffix.lower() == ".md" else set()
    for pattern in _TYPE_GLOBS.get(htype, _TYPE_GLOBS["generic"]):
        found = {p for p in root.glob(pattern) if p.is_file()}
        if found:
            return found
    if htype in _RECURSIVE_FALLBACK:         # e.g. zcode without projects/
        return {p for p in root.rglob("*.md") if p.is_file()}
    return set()                            # preset matched nothing here


def memory_files(h: Harness) -> list[Path]:
    """All markdown files this harness owns.

    A root may be a directory (scanned per its type preset), a single `.md`
    file (e.g. `CLAUDE.md`), or a **glob pattern** — `paths = ["~/.claude/**/*.md"]`
    — so a new tool needs no code change, only config."""
    files: set[Path] = set()
    for root in h.roots:
        if _is_glob(str(root)):
            files.update(Path(m) for m in glob.glob(str(root), recursive=True)
                         if os.path.isfile(m) and m.lower().endswith(".md"))
            continue
        files.update(_scan_root(root, h.type))
    return sorted(files)


def fingerprint(files: list[Path]) -> str:
    """Content fingerprint over (relative name, content hash), order-stable."""
    lines = []
    for p in files:
        try:
            digest = hashlib.sha1(p.read_bytes()).hexdigest()
        except OSError:
            digest = "unreadable"
        lines.append(f"{p.name}:{digest}")
    return hashlib.sha1("\n".join(lines).encode()).hexdigest()[:16]


def summary_path(cfg, h: Harness) -> Path:
    from loci.memories import slugify
    return Path(cfg.memories["path"]).expanduser() / "harness" / f"{slugify(h.name)}.md"


def _stored_fingerprint(cfg, h: Harness) -> str | None:
    p = summary_path(cfg, h)
    if not p.exists():
        return None
    m = re.search(r"^fingerprint:\s*(\S+)",
                  p.read_text(encoding="utf-8", errors="ignore"), re.M)
    return m.group(1) if m else None


def stats(cfg, store, harnesses: list[Harness]) -> list[dict]:
    """Per-harness stats: file count, total chars, last update, indexed chunks,
    summary freshness. Zero LLM cost."""
    per_source = store.per_source()
    roots_by_h = [(h, [_root_prefix(r) for r in h.roots]) for h in harnesses]
    out = []
    for h, roots in roots_by_h:
        files = memory_files(h)
        chunks = sum(n for src, n in per_source.items()
                     if any(src.startswith(r) for r in roots))
        last = max((p.stat().st_mtime for p in files if p.exists()), default=0.0)
        fp = fingerprint(files)
        stored = _stored_fingerprint(cfg, h)
        out.append({
            "name": h.name, "display": h.display or h.name,
            "type": h.type, "icon": h.icon,
            "files": len(files), "chars": sum(
                p.stat().st_size for p in files if p.exists()),
            "chunks": chunks,
            "last_updated": datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M")
                            if last else "",
            "summary": {"path": str(summary_path(cfg, h)),
                        "status": ("fresh" if stored == fp else
                                   "stale" if stored else "missing")},
        })
    return out


def _digest_input(files: list[Path]) -> str:
    """Newest-first excerpt bundle within the token budget."""
    parts, budget = [], _TOTAL_CHARS
    for p in sorted(files, key=lambda p: p.stat().st_mtime if p.exists() else 0,
                    reverse=True):
        if budget <= 0:
            break
        text = p.read_text(encoding="utf-8", errors="ignore").strip()
        part = f"### {p.name}\n{text[:_PER_FILE_CHARS]}\n\n"
        parts.append(part[:budget])
        budget -= len(parts[-1])
    return "".join(parts)


def _llm_digest(llm_cfg: dict, bundle: str) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=llm_cfg["base_url"], api_key=llm_cfg["api_key"])
    resp = client.chat.completions.create(
        model=llm_cfg["model"],
        messages=[{"role": "system", "content": SUMMARY_PROMPT},
                  {"role": "user", "content": bundle}],
        temperature=0.2,
    )
    body = (resp.choices[0].message.content or "").strip()
    return re.sub(r"^```(?:markdown)?\n|\n```$", "", body).strip()


def summarize(cfg, h: Harness, force: bool = False) -> dict:
    """Write/refresh one harness summary note. Fingerprint-gated: unchanged
    harnesses return early with zero LLM cost. Best-effort indexing after."""
    files = memory_files(h)
    fp = fingerprint(files)
    out = summary_path(cfg, h)
    if not files:
        return {"harness": h.name, "status": "empty", "path": str(out)}
    if not force and _stored_fingerprint(cfg, h) == fp:
        return {"harness": h.name, "status": "unchanged", "path": str(out)}
    try:
        body = _llm_digest(cfg.llm, _digest_input(files))
    except Exception as e:
        return {"harness": h.name, "status": "error",
                "error": f"{type(e).__name__}: {e}", "path": str(out)}
    out.parent.mkdir(parents=True, exist_ok=True)
    iso = datetime.now().strftime("%Y-%m-%d %H:%M")
    front = ("---\n"
             "tags: [memory, harness, summary]\n"
             f"title: {h.display or h.name} memory digest\n"
             f"updated: {iso}\n"
             f"harness: {h.name}\n"
             f"type: {h.type}\n"
             f'icon: "{h.icon}"\n'
             f"fingerprint: {fp}\n"
             f"files: {len(files)}\n"
             "---\n")
    tmp = out.with_suffix(".md.tmp")
    tmp.write_text(f"{front}# {h.display or h.name} · memory digest\n\n{body}\n",
                   encoding="utf-8")
    tmp.replace(out)
    try:
        from loci.memories import index_memory_file
        index_memory_file(cfg, str(out))
    except Exception:
        pass                                # replayable via `loci ingest`
    return {"harness": h.name, "status": "written", "path": str(out)}


def summarize_all(cfg, harnesses: list[Harness], force: bool = False) -> list[dict]:
    return [summarize(cfg, h, force=force) for h in harnesses]


def stats_table(rows: list[dict]) -> str:
    """ASCII table for CLI / MCP output."""
    if not rows:
        return ("(no [[harness]] entries in config.toml — add one per AI tool:\n"
                '  [[harness]]\n  name = "zcode"\n  type = "zcode"\n'
                '  paths = ["~/.zcode/cli/memories"])')
    head = f'{"harness":<20} {"type":<9} {"files":>5} {"chunks":>6}  {"last update":<16} summary'
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(f'{r.get("display") or r["name"]:<20} {r["type"]:<9} {r["files"]:>5} '
                     f'{r["chunks"]:>6}  {r["last_updated"]:<16} '
                     f'{r["summary"]["status"]}')
    return "\n".join(lines)
