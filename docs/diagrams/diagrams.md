# Diagram sources

Editable Mermaid sources for the README diagrams. GitHub renders the
README's mermaid blocks natively; the two hero diagrams are also shipped
as pre-styled dark SVGs in docs/assets/.

## system-interactions

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#000000','primaryColor':'#000000','primaryTextColor':'#00FF41','primaryBorderColor':'#00FF41','lineColor':'#00FF41','secondaryColor':'#001a00','tertiaryColor':'#000000','clusterBkg':'#000000','clusterBorder':'#00FF41','edgeLabelBackground':'#000000','fontSize':'14px','fontFamily':'trebuchet ms, verdana, arial, sans-serif'},'themeCSS':'.nodeLabel { color: #00FF41 !important; } .edgeLabel { background: #000 !important; color: #00FF41 !important; } .cluster-label { color: #00FF41 !important; }'}}%%
flowchart LR
    subgraph sources["📥 Your machine"]
        notes["Obsidian / markdown notes"]
        docs["PDF tables · docx · project docs"]
        chats["ChatGPT / Claude exports"]
        mem["memories/ — agent-written notes"]
        wikidir["wiki/ — consolidated pages"]
    end

    subgraph loci["🧠 loci — local index, nothing leaves the machine"]
        ingest["ingest / watch<br>loaders → chunker → embedder"]
        store[("ChromaDB<br>hybrid index")]
        retrieve["hybrid retrieval<br>vector + BM25 → RRF"]
        mcp["loci-mcp<br>8 tools · resources · prompts"]
    end

    subgraph hosts["🖥️ Your AI hosts"]
        ide["Claude Code · Qoder · Trae<br>Cursor · Cline"]
        desktop["Claude Desktop"]
        term["Terminal<br>search / ask / chat / wiki"]
    end

    api["☁️ OpenAI-compatible API<br>Zhipu / DeepSeek / Kimi / OpenAI<br>or 100% offline via Ollama"]

    sources --> ingest --> store
    mem -. auto-indexed .-> store
    wikidir -. auto-indexed .-> store
    store --> retrieve
    retrieve --> term
    retrieve --> mcp
    mcp <--> ide
    mcp <-.-> desktop
    retrieve -. "embedding + chat calls only" .-> api
```

## workflow

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#000000','primaryColor':'#000000','primaryTextColor':'#00FF41','primaryBorderColor':'#00FF41','lineColor':'#00FF41','secondaryColor':'#001a00','tertiaryColor':'#000000','clusterBkg':'#000000','clusterBorder':'#00FF41','edgeLabelBackground':'#000000','fontSize':'14px','fontFamily':'trebuchet ms, verdana, arial, sans-serif'},'themeCSS':'.nodeLabel { color: #00FF41 !important; } .edgeLabel { background: #000 !important; color: #00FF41 !important; } .cluster-label { color: #00FF41 !important; }'}}%%
flowchart TD
    A["pip install loci-rag"] --> B["cp config.example.toml config.toml<br>fill API keys + source dirs"]
    B --> C["loci ingest — hybrid index built"]
    C --> D["loci watch — index stays fresh (optional)"]
    C --> E{"What do you need?"}
    E -->|"a synthesized answer"| F["loci ask --verify<br>claim-by-claim audit"]
    E -->|"raw excerpts to quote"| G["loci search --tag memory"]
    E -->|"back-and-forth"| H["loci chat"]
    E -->|"scattered notes on a topic"| I["loci wiki topic<br>consolidate into a wiki page"]
    F --> J["loci remember —<br>keep what you learned"]
    I --> J
```

## cross-ide-memory-sequence

```mermaid
%%{init: {'theme':'base','themeVariables':{'background':'#000000','primaryColor':'#000000','primaryTextColor':'#00FF41','primaryBorderColor':'#00FF41','lineColor':'#00FF41','actorBkg':'#000000','actorBorder':'#00FF41','actorTextColor':'#00FF41','signalColor':'#00FF41','signalTextColor':'#00FF41','noteBkgColor':'#001a00','noteBorderColor':'#00FF41','activationBkgColor':'#001a00','edgeLabelBackground':'#000000','fontSize':'14px','fontFamily':'trebuchet ms, verdana, arial, sans-serif'},'themeCSS':'.messageText { fill: #00FF41 !important; } .actor { fill: #000 !important; stroke: #00FF41 !important; } text.actor { fill: #00FF41 !important; }'}}%%
sequenceDiagram
    participant CC as Claude Code
    participant L as loci-mcp
    participant S as ChromaDB (local)
    participant T as Trae / Qoder / any IDE
    CC->>L: brain_remember("deploy rotates Mondays")
    L->>S: write memory.md + embed + index
    Note over S: persists across sessions and IDEs
    T->>L: brain_search("password rotation")
    L->>S: hybrid retrieval
    L-->>T: cited answer — the memory is recalled
```
