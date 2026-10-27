# 使用指南

[返回首页](../README.zh-CN.md)

## 模型供应商


`[llm]` 与 `[embed]` 可指向不同供应商（如问答用 DeepSeek、向量化用 OpenAI，混搭完全可以）。唯一规则：`[embed]` 端点必须提供 OpenAI 风格的 `/embeddings` API。

| 供应商 | `base_url` | 问答模型 | 向量模型 | 备注 |
|---|---|---|---|---|
| OpenAI（默认） | `https://api.openai.com/v1` | `gpt-4o-mini` | `text-embedding-3-small` | |
| 智谱 (GLM) | `https://open.bigmodel.cn/api/paas/v4` | `glm-4.6` | `embedding-3` | |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` | — | 无 `/embeddings`，`[embed]` 需配别家 |
| Kimi (Moonshot) | `https://api.moonshot.cn/v1` | `kimi-k2` | — | 同上，`[embed]` 配别家 |
| Ollama（本地） | `http://localhost:11434/v1` | `llama3.1`、`qwen2.5:7b` 等 | `nomic-embed-text` | 100% 离线；api_key 随便填 |


## Demo

真实会话，索引自 [minimax-h3-turing](https://github.com/IvenKooLab/minimax-h3-turing) 的文档（路径已缩短显示）：

```
$ python main.py search "what the 22G card can and cannot do" -k 3

[1] minimax-h3-turing/docs/en/01-hardware-limits.md > 01 · What a 2080Ti 22G Can and Cannot Do    (similarity 0.562)
[2] minimax-h3-turing/docs/en/02-w4a8-vs-w4a4.md > 02 · Quantization Measured > You Can Try Without 22G  (similarity 0.446)
[3] minimax-h3-turing/docs/en/01-hardware-limits.md > ... > 3. VRAM is just barely enough — manage it  (similarity 0.504)

$ python main.py ask "How should I choose between T8 aggressive mode and the final-render mode, and why?"

Answer:
* Drafts / preview / shot selection: use T8 aggressive mode — a 43% speedup
  (2.7 min/clip), and "a different picture of equal quality" is fine for picking shots.
* Final shots: use final-render mode (no T8). T8 makes the numerical trajectory
  fork, so re-running with the same seed produces a different clip — which breaks
  the reproducibility final outputs need.

[source: docs/en/08-t8-blockcache-4step.md > Practical Advice (4-step Turbo route)]
[source: docs/en/06-faq.md > 12. Cache-style accelerators break "same-seed re-runs"]
```

混合检索意味着中文查询也能命中英文文档（反之亦然）——关键词证据（BM25）补上向量检索的盲区，而且每条引用都指向**章节**，不只是文件。

### 混合检索真的有用吗？（10 条双语查询实测）

```
$ python scripts/eval_retrieval.py scripts/eval_cases.example.jsonl
vector-only: 9/10  →  hybrid: 10/10
```

混合检索还修正了关键词型查询的第 1 名（例如 "T8 block cache threshold speedup"：纯向量把一篇 FAQ 排第一，混合检索把真正的 T8 实测文档排第一）。用你自己的语料和查询文件跑一遍即可验证。

### 重排序：两种 Provider

`--rerank` 会对融合后的候选做精排：

| Provider | 方式 | 代价 |
|---|---|---|
| `llm`（默认） | 由你的对话模型做 0–3 分逐条评分 | 一次额外 LLM 调用 |
| `local` | 交叉编码器，需 `pip install 'loci-rag[rerank]'` | GPU 上 5 对约 30–70 毫秒——离线、免费 |


## 命令

| 命令 | 作用 |
|---|---|
| `demo` | 内置示例语料的离线演示——只用关键词检索，不需要配置或 key（脚本里加 `--no-input`） |
| `ingest` | 扫描来源目录，索引新增/变更文件，清理已删除文件（`--force` 全量重建） |
| `search "query"` | 纯检索——带 `路径 > 章节` 面包屑的排序结果 |
| `ask "question"` | 检索 + LLM 回答，带 `[source: path > section]` 引用 |
| `ask "…" --verify` | 追加逐条主张审计（✓ 支持 / ~ 部分 / ✗ 不支持） |
| `links "note"` | 显示某笔记的 `[[双链]]` 出入图谱 |
| `chat` | 多轮问答循环（`/clear`、`/exit`） |
| `wiki topic` | 把索引中关于某主题的内容蒸馏成一页 wiki |
| `remember text` | 写入持久记忆笔记并立即索引 |
| `ask "…" --rewrite` | LLM 改写查询（关键词版 + 跨语言变体）后再检索 |
| `feedback good\|bad` | 为上一次 ask 用到的 chunk 打分；被打差评的 chunk 后续降权 |
| `wiki --suggest` | 推荐值得写 wiki 页但还没有页面的主题 |
| `bench cases.jsonl` | 检索基准测试：hit@k，纯向量 vs 混合 |
| `sync push\|pull` | 经 git 在多台机器间同步 memories/wiki（[sync] remote） |
| `serve-http` | HTTP REST API（search/ask/remember/stats），Bearer 鉴权 |
| `graph build` / `graph show 实体` | 知识图谱：对 memories/wiki 抽取实体关系（graph.json） |
| `stats` | 索引概况：每个来源的 chunk 数、模型、检索设置 |
| `doctor` | 健康检查：配置、来源目录、embed/LLM 端点、存储 |
| `watch` | 轮询来源保持索引最新（可选） |
| `python mcp_server.py` | MCP server（stdio，见下文） |

过滤操作符（`search` 和 `ask` 均可自由组合）：

| 参数 | 过滤范围 |
|---|---|
| `--tag foo` | frontmatter 标签含 `foo` 的文件 |
| `--in docs/en` | 路径含该子串的文件 |
| `--since 2026-08` / `--since 2026-08-15` | 该日期之后修改的文件 |
| `-e "exact phrase"` | 含精确短语的 chunk |
| `-k N` | 返回 N 条（默认 5） |


## 一份记忆，所有 IDE

每个 MCP 宿主挂载的都是**同一个** loci server（同一 `config.toml`、同一索引），因此一个工具写入的记忆，其他所有工具都能召回：

```bash
# Claude Code
claude mcp add loci -- loci-mcp
```

```jsonc
// Cursor / Cline / Qoder / Trae（mcpServers JSON——各平台形状一致）
{ "mcpServers": { "loci": { "command": "loci-mcp" } } }
```

然后，在任意一个里：*"记住 staging 密码每周一轮换"* → `brain_remember` → 稍后在**另一个** IDE 里：*"staging 密码什么时候轮换？"* → 得到带引用的回答。记忆以纯 markdown 存放在 `memories` 目录（git 友好、无锁定），统一打 `memory` 标签，`loci search --tag memory` 可专搜记忆。

> **跨 IDE 提示**：默认的 `store` / `memories` 路径相对于 loci 的启动目录。给 MCP 挂载加 `env: { "LOCI_HOME": "~/.loci" }` 即可把整个实例（config/索引/memories/wiki）锚定在同一目录，所有 IDE 共享同一份记忆库，无需手动改路径。


## Harness 记忆中枢

同时用多个 AI 编码工具？每个都有自己的记忆目录。loci **自动发现**它们——内置注册表（ZCode、Codex、DeepSeek Harness、Claude Code）按机器探测（home 目录 / 应用包 / `DSH_HOME` 环境变量），探测命中即以真实记忆统计出现在卡片里。不在磁盘上编造任何东西：没有 markdown 记忆的工具就如实显示为零。需要覆盖探测或接入其他工具时再显式注册：

```toml
[[harness]]
name = "zcode"
type = "zcode"                        # 内置识别 projects/*/memory/*.md 结构
paths = ["~/.zcode/cli/memories"]
icon = "⚡"                            # emoji，或 icons 目录下的图片文件名

[[harness]]
name = "my-tool"
type = "generic"                      # 递归 *.md 扫描
paths = ["~/notes/from-my-agent"]
```

- `loci harness`——每个工具的统计（文件数、索引 chunks、最近更新、摘要新鲜度），零 LLM 成本
- `loci harness --summarize`——把每个工具的记忆蒸馏成一篇摘要笔记进共享池（`memories/harness/<name>.md`），按内容指纹增量：记忆没变就零成本，所以 `watch` 可以配合 `[watch] auto_summarize = true` 每轮刷新
- MCP `brain_harness`——任一 agent 里同样两个动作（"各工具最近都在忙什么？"）


## Web 管理台

`loci serve-http` 现在内置管理台：`http://127.0.0.1:8765/ui`（零新增依赖、无构建步骤）——harness 图标卡片、共享记忆增删改（删除进 `.trash`）、索引统计与一键 ingest / 重新总结、搜索与问答框。

多 token + 角色的权限管理，写进 `config.toml`：

```toml
[[auth.tokens]]
token = "长随机密钥-1"
role = "admin"                        # 额外可 ingest、重新总结、看审计
label = "我的笔记本"

[[auth.tokens]]
token = "长随机密钥-2"
role = "viewer"                       # 只读浏览
label = "手机"
```

角色层层递进：`viewer`（只读）< `editor`（+记忆增删改）< `admin`（+ingest / 重总结 / 审计）。旧的 `[http]` 单 token 继续有效，视为 admin。**本机打开无需登录**——来自 127.0.0.1 的匿名连接默认信任为 admin（走反代或 SSH 隧道时请设 `[http] local_admin = false`，隧道流量同样以 loopback 形式到达）。写操作和管理操作会审计到服务日志与 `GET /audit`。管理台与 API 一样只绑 127.0.0.1——其他设备访问请走 SSH 隧道或带 TLS 的反代。界面右上角可切换 中文/EN。

读操作与写操作分开记录：「agent 搜不到东西」是读侧的谜题。管理台的 **查询** 页（以及 `GET /queries`）列出最近 500 次检索与提问：谁查的、命中几条、首条结果在哪、耗时多少——不记录返回的正文。「Codex 什么都搜不到」因此会变成「Codex 查的是空索引」。设 `[http] query_log = "./queries.jsonl"` 可把同样的记录追加到文件。

同一台机器跑两个实例（不同 `LOCI_HOME`）是正常用法。端口被占用时 `serve-http` 会直接说明情况并给出解法，而不是抛栈；用 `--port 0` 让系统挑一个，实际端口会打印出来。


## 真实部署场景

两个影响了 loci 设计的生产部署：

- **AI 编码工具之间的记忆互通**——两个 agent（不同 CLI）挂载同一个 loci MCP server；各自的本地记忆目录都是 `[[sources]]` 条目，一侧写入的记忆另一侧随时可检索，`brain_remember` 写入共享记忆池。
- **聊天软件 → 知识库流水线**——发给 bot 的文档自动提交进私有 git 仓；每台机器定时拉取该仓库、各自维护**本地** loci 索引，手机上发的任何东西几分钟后就能在所有 IDE 和 agent 里检索。这条流水线还踩出一个真实世界的坑：聊天软件传输可能损坏 `.docx` 的某个 zip 成员——loci 现在会抢救正文文本而不是跳过整个文件。

多机部署的经验法则：**只同步源文件，绝不同步索引和密钥**。向量索引是机器本地的（`loci ingest` 随时可重建）；凭据永远不该进仓库。


## 接入任意 MCP 宿主

加入 `claude_desktop_config.json`（Claude Desktop）或你的 MCP 客户端配置：

```json
{
  "mcpServers": {
    "loci": {
      "command": "python",
      "args": ["/path/to/second-brain-rag/mcp_server.py"],
      "env": { "LOCI_HOME": "/path/to/instance" }
    }
  }
}
```

`LOCI_HOME` 把 config、索引、memories、wiki 统一锚定在一个目录——与进程工作目录无关。MCP 挂载和 launchd/cron/systemd 下跑 `serve-http`（包装脚本的 `cd` 不生效的场景）都适用。

除工具外，server 还支持完整协议：

- **Resources** —— `resources/list` 暴露 `brain://stats` 和每个已索引文件的 `brain://note/…` 资源（经 `resources/read` 读取原始 markdown）
- **Prompts** —— 三个预置模板：`brain-briefing`、`study-plan`、`contradiction-check`


## 工具一览

| 工具 | 用途 |
|---|---|
| `brain_search(query, k?, tag?, in?)` | 带面包屑的排序摘录 |
| `brain_ask(question, verify?)` | 基于索引的引用式回答；`verify=true` 追加逐条审计 |
| `brain_wiki(topic)` | **记忆巩固**——把索引蒸馏成互链 wiki 页 |
| `brain_remember(text, title?, tags?)` | **写入持久记忆**——跨会话、跨 IDE 共享 |
| `brain_forget(query)` | 软删除匹配记忆（进 `.trash` 文件夹） |
| `brain_harness(action, name?, force?)` | 各 AI 工具记忆统计，或刷新其摘要笔记 |
| `brain_links(note)` | 笔记的出入 `[[wikilink]]` 图谱 |
| `brain_stats()` | 索引概况（每个来源的 chunk 数） |
| `brain_ingest(force?)` | 增量重建索引 |


## 全离线：Ollama

索引天然本地——向量和对话调用也可以。任何 OpenAI 兼容服务都行，[Ollama](https://ollama.com) 已端到端验证：

```toml
[llm]
base_url = "http://localhost:11434/v1"
api_key = "ollama"          # 任意非空占位符
model = "qwen2.5:0.5b"

[embed]
base_url = "http://localhost:11434/v1"
api_key = "ollama"
model = "all-minilm"
```

此配置下 `ingest` / `search` / `ask` 零云端调用。换更大的本地对话模型即可获得更好的回答——管线与模型无关。


## 配置

| 键 | 含义 |
|---|---|
| `[llm]` | base_url / api_key / model——任意 OpenAI 兼容端点 |
| `[embed]` | 同上；model 须为 embedding 模型（如 `text-embedding-3-small`） |
| `[[sources]]` | 文档目录列表，递归扫描 `.md` / `.txt` / `.html` / `.org`（装了 extras 还支持 `.pdf` / `.docx`） |
| `[[sources]] chunk_size` / `chunk_overlap` | 按目录覆盖切分参数 |
| `[chunk]` | 全局切分参数（默认 800 字符 / 100 重叠） |
| `[top_k]` | 每次搜索的命中数（默认 5） |
| `[retrieval]` | `hybrid`（向量+BM25 融合，默认开）、`rrf_k`、`rerank`（LLM 重排，默认关） |
| `[bm25]` | 关键词那一路的分词器。`default` 是冻结的（英文整词 + 中文单字），不动它就等于保持和旧版本完全一致的排序；想加强就显式选：`hyphen_join`（连字符词同时索引合并写法，搜 `wifi` 能命中 `Wi-Fi`）、`cjk_bigram`（中文双字，`检索` 能命中 `全文检索` 内部，零依赖）、`jieba`（词级分词，需 `loci-rag[zh]`） |
| `[memories]` / `[wiki]` | 记忆笔记与 wiki 页的目录（自动并入索引） |
| `[watch]` | 轮询间隔秒数 |

API key 也可用环境变量 `BRAIN_LLM_API_KEY` / `BRAIN_EMBED_API_KEY`（覆盖配置文件）。

- **知识图谱**：`loci graph build` 从记忆与 wiki 页抽取实体关系三元组，存入人类可读的 `graph.json`；`brain_graph(entity)` 展示概念间的连接（每条边带来源引用），wiki 生成时以图谱关系作补充上下文
- **OCR**（`[ocr]` extra）：图片与扫描版 PDF 也能识别入库
- **HTML / org-mode 加载器**（标准库实现，零新依赖）

