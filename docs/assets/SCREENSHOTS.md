# Console documentation screenshot

`console-demo-light.png` shows the real checked-in console UI, served by
`scripts/preview_console.py` with fixed, fictional fixtures. The screenshot
includes a file tree and a fictional Project Atlas note.

No production server, local config, personal memory, credential or vector
index is used. Counts and timestamps are illustrative, not benchmark evidence.
The preview does not import loci's configuration/database/model code; write
and model endpoints are disabled.

To reproduce:

```bash
python scripts/preview_console.py --port 8877
```

Open `http://127.0.0.1:8877/ui`, switch to English, click the Codex card and
select `atlas/decisions.md`. Capture the console with the demo label visible.
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
