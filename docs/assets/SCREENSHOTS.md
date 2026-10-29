# Console documentation screenshot

`console-demo-light.png` and `console-demo-dark.png` show the **Dashboard** tab
of the current console: the left sidebar (Dashboard / Search / Memories /
Sources / Queries / Index / Audit), the range filter, the stat cards, top
queries, zero-hit queries, chunks per source and the 14-day activity strip.

Both are rendered from a static fixture page that imports the console's real
`style.css` and reproduces its real markup — the classes, spacing and colours
are the shipped ones, not a mock-up. The fixture data is fictional: 128
queries, 482 chunks, an "aurora" sensor project, three source directories.

No production server, local config, personal memory, credential or vector
index is involved. Counts and timestamps are illustrative, not benchmark
evidence.

**Known limitation:** these are rendered from the stylesheet rather than
captured from a live browser session (the machine that regenerated them has no
headless browser). Because `app.js` does not run, only the Dashboard tab is
shown; the other tabs need a real browser to capture. If you regenerate them
properly, use:

```bash
python scripts/preview_console.py --port 8877
```

Open `http://127.0.0.1:8877/ui`, switch to English, then capture at 1280×820.
The console itself currently supports English and Simplified Chinese; README
translations do not imply additional UI language support.

## `loci demo` card

`demo-offline.png` is rendered from the real output of `loci demo --no-input`
against the corpus shipped in `src/loci/demo_notes/` — no hand-written text.
The corpus path is shortened to `./loci-demo-notes` and the per-query timings
are normalised, since both are environment noise; everything else is verbatim.

To reproduce:

```bash
python scripts/render_demo_card.py
```

## `loci-mcp` session

`mcp-tools.png` is captured from the real `loci-mcp` binary answering a
three-message session (`initialize`, `tools/list`, `prompts/list`), then
rendered — the tool names, descriptions and protocol version are the binary's
own output, not a mock. Reproduce with:

```bash
cargo build -p loci-cli --manifest-path native/Cargo.toml
printf '%s\n' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | ./native/target/debug/loci-mcp --config your/config.toml
```
