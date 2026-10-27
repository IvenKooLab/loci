<p align="center">
  <img src="docs/assets/loci-banner.svg" alt="loci — shared memory for your AI tools" width="100%">
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.zh-TW.md">繁體中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a>
</p>

<p align="center">
  <a href="https://github.com/IvenKooLab/loci/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/IvenKooLab/loci/ci.yml?branch=main&amp;label=CI" alt="CI"></a>
  <a href="https://pypi.org/project/loci-rag/"><img src="https://img.shields.io/pypi/v/loci-rag?color=367d65" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-367d65" alt="Python 3.11+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-367d65" alt="MIT license"></a>
</p>

**將散落的筆記、專案文件與 Agent 記憶，整理成可搜尋、提問及追溯來源的知識庫。終端機、瀏覽器與 MCP 用戶端都能使用。**

loci 結合向量檢索與 BM25，回答附上「檔案 > 章節」引用。檔案與索引保存在本機；向量化及對話請求會送往你設定的服務，也可以搭配本機模型離線運作。

[快速開始](#快速開始) · [Web 管理介面](#web-管理介面) · [接入-ai-工具](#接入-ai-工具) · [詳細指南（簡中）](docs/guide.zh-CN.md)

![loci 管理介面與記憶檔案預覽](docs/assets/console-demo-light.png)

*實際介面搭配虛構示範資料；未連接個人知識庫、帳號或金鑰。圖中的統計數字僅供展示。*

<details>
<summary>查看深色介面</summary>

![loci console — dark theme, fictional demo data](docs/assets/console-demo-dark.png)

</details>

## 可以用來做什麼

| 需求 | loci 的做法 |
|---|---|
| 找回以前討論的決策 | 跨目錄混合檢索，支援標籤、路徑與日期篩選 |
| 提問後核對依據 | 回答引用原始章節，可逐項驗證結論 |
| 在不同 AI 工具間保留脈絡 | MCP 共用同一實例，長期記憶儲存為 Markdown |
| 檢視各個 Agent 記住的內容 | 自動探索 harness，瀏覽檔案、統計與摘要 |
| 以視覺化介面管理知識庫 | 內建搜尋、問答、記憶編輯、索引與稽核介面 |

原生支援 Markdown、純文字、HTML、org-mode 與聊天匯出；可選擴充套件提供 PDF、Word 與 OCR 支援。可繼續使用現有編輯器或 Obsidian 知識庫。

## 快速開始

### 先什麼都不設定，直接看效果

```bash
pip install loci-rag
loci demo
```

`loci demo` 會把六篇虛構筆記複製到 `./loci-demo-notes`，切塊後回答三個範例問題，引用精確到 `檔案 > 小節` —— 不需要 `config.toml`、不需要 API key、不連網。它只用關鍵詞檢索（BM25，也就是混合檢索裡與向量結果融合的那一路排序），這正是重點：在你交出任何 key 之前，先讓東西跑起來。之後補上 `[embed]`，同一份索引就變成混合檢索。

### 索引你自己的筆記

需要 **Python 3.11+**。從原始碼開始即可取得設定範例：

```bash
git clone https://github.com/IvenKooLab/loci.git
cd loci
python -m pip install -e .
cp config.example.toml config.toml
```

編輯 `config.toml`：填寫 `[llm]`、`[embed]`，並將 `[[sources]].path` 改為筆記目錄。向量服務須支援 `/embeddings`；對話與向量服務可使用不同供應商。

```bash
loci ingest
loci search "部署決策"
loci ask "我們決定如何部署？原因是什麼？"
```

已有設定時可直接安裝 `python -m pip install loci-rag`，並以 `LOCI_HOME` 指定實例目錄。PDF、Word 擴充：`python -m pip install 'loci-rag[pdf,docx]'`。

> 可透過 `BRAIN_LLM_API_KEY`、`BRAIN_EMBED_API_KEY` 傳入金鑰。更換向量模型後，請執行 `loci ingest --force` 重建索引。

## Web 管理介面

```bash
loci serve-http
```

開啟 **[127.0.0.1:8765/ui](http://127.0.0.1:8765/ui)**。介面支援英文／簡體中文、淺色／深色切換，無須額外建置前端。

預設信任本機回環位址的匿名連線，並授予管理員權限。透過反向代理或 SSH 通道存取時，請設定 `[http] local_admin = false` 並使用角色權杖。[存取控制說明（簡中）](docs/guide.zh-CN.md#web-管理台)。

[loci-dsh](https://github.com/IvenKooLab/loci-dsh) 可透過同一 HTTP 後端，將搜尋、問答與速記加入 DeepSeek Harness 工作台。

## 接入 AI 工具

讓 MCP 用戶端指向**相同的 `LOCI_HOME`**，共用設定、索引與記憶：

```json
{
  "mcpServers": {
    "loci": {
      "command": "loci-mcp",
      "env": { "LOCI_HOME": "/absolute/path/to/your/loci-instance" }
    }
  }
}
```

實例目錄須包含 `config.toml`。若找不到 `loci-mcp`，請改用執行檔的絕對路徑。

| MCP 工具 | 用途 |
|---|---|
| `brain_search` · `brain_ask` | 搜尋片段與附帶引用的回答 |
| `brain_remember` · `brain_forget` | 儲存或撤回長期記憶 |
| `brain_links` · `brain_graph` | 探索筆記連結與知識關係 |
| `brain_wiki` · `brain_harness` | 整理專題知識與 Agent 記憶 |
| `brain_stats` · `brain_ingest` | 查看及更新索引 |

![loci-mcp — real JSON-RPC session](docs/assets/mcp-tools.png)

*真實 `loci-mcp` 的輸出：`initialize`、`tools/list`、`prompts/list`。*

### 原生版本（Rust）

同一套檢索管線與同一套 MCP 介面，但不需要安裝 Python 執行環境——單一二進位檔，
索引是一個 SQLite 檔案而不是一個資料庫目錄：

```bash
cargo build --release -p loci-cli     # 在 native/ 下
./target/release/loci-mcp --config ~/.loci/config.toml
```

狀態：核心與 MCP 已完成，封裝與桌面外殼進行中。移植了哪些、以及釘住行為的測試見 [`native/`](native/)。
**兩個版本的索引不互通**——原生版不讀 ChromaDB 的索引。

## 日常工作流程

```bash
loci watch
loci remember "展示使用預備環境" --title "展示環境約定"
loci search "展示環境" --tag memory
loci ask "準備展示時應注意什麼？" --verify
loci harness
```

索引會增量更新，記憶保留為可讀的 Markdown。跨機器請同步原始檔案與記憶，分別建立本機索引；不要將金鑰存入儲存庫。

## 文件

[使用指南（簡中）](docs/guide.zh-CN.md) · [English guide](docs/guide.en.md) · [設定範例](config.example.toml) · [架構](docs/ARCHITECTURE.md) · [更新紀錄](CHANGELOG.md) · [路線圖](docs/roadmap.md) · [參與貢獻](CONTRIBUTING.md)

執行時使用 OpenAI 相容 SDK 與 ChromaDB，不依賴 LangChain 或 LlamaIndex。測試離線執行，無須 API key：

```bash
python -m pip install -e '.[dev,pdf]'
pytest
```

[GitHub](https://github.com/IvenKooLab/loci) · [Gitee](https://gitee.com/IvenKooLab/loci) · [MIT](LICENSE)
