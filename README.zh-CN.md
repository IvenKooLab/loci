<p align="center">
  <img src="docs/assets/loci-banner.svg" alt="loci — AI 工具之间共享的记忆层" width="100%">
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.zh-TW.md">繁體中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a>
</p>

<p align="center">
  <a href="https://github.com/IvenKooLab/loci/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/IvenKooLab/loci/ci.yml?branch=main&amp;label=CI" alt="CI"></a>
  <a href="https://pypi.org/project/loci-rag/"><img src="https://img.shields.io/pypi/v/loci-rag?color=367d65" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-367d65" alt="Python 3.11+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-367d65" alt="MIT 许可证"></a>
</p>

**把散落的笔记、项目文档和 Agent 记忆，变成可以搜索、提问、追溯来源的知识库——以 MCP 服务器的形态，终端和浏览器同样可用。**

**MCP 才是主线。** 把 `loci-mcp` 挂进 Claude Desktop、Cursor、Cline 或任意 MCP 宿主，你的助手就拿整个知识库当工具用。管理台和桌面客户端只是同一份索引的另一种外壳，不是必需品。

loci 将向量检索与 BM25 结合，回答附带「文件 > 章节」引用。文件和索引保留在本机；向量化与对话请求发往你配置的服务，也可以通过本地模型实现全离线运行。

[快速开始](#快速开始) · [接入 AI 工具](#接入-ai-工具) · [Web 管理台](#web-管理台) · [完整使用指南](docs/guide.zh-CN.md) · [English](README.md)

![loci console — synthetic-data demo](docs/assets/console-demo-light.png)

*真实管理台界面，使用虚构演示数据；未连接个人知识库、账号或密钥，统计数字仅用于展示。*

<details>
<summary>查看深色界面</summary>

![loci console — dark theme, fictional demo data](docs/assets/console-demo-dark.png)

</details>

## 你可以用它做什么

| 想解决的问题 | loci 的做法 |
|---|---|
| 找不到以前讨论过的决策 | 跨目录混合检索，支持标签、路径和日期筛选 |
| 想提问，又需要核对依据 | 回答引用具体章节，可逐条核查结论 |
| 换一个 AI 工具就丢上下文 | MCP 共享同一实例，长期记忆以 Markdown 保存 |
| 不清楚各个编码 Agent 记住了什么 | 自动发现 harness，查看文件、统计与摘要 |
| 不想每次操作都用命令行 | 内置管理台，搜索、问答、编辑记忆、重建索引和查看审计 |

默认支持 Markdown、纯文本、HTML、org-mode 和聊天导出；安装可选扩展后支持 PDF、Word 与 OCR。现有笔记编辑器和 Obsidian 知识库可以继续使用。

## 快速开始

### 先什么都不配，直接看效果

```bash
pip install loci-rag
loci demo
```

`loci demo` 会把六篇虚构笔记复制到 `./loci-demo-notes`，切块后回答三个示例问题，引用精确到 `文件 > 小节` —— 不需要 `config.toml`、不需要 API key、不联网。它只用关键词检索（BM25，也就是混合检索里和向量结果融合的那一路排序），这正是重点：在你交出任何 key 之前，先让东西跑起来。之后补上 `[embed]`，同一份索引就变成混合检索。

### 索引你自己的笔记

需要 **Python 3.11+**。从源码开始，可以直接拿到配置示例：

```bash
git clone https://github.com/IvenKooLab/loci.git
cd loci
python -m pip install -e .
cp config.example.toml config.toml
```

编辑 `config.toml`：填写 `[llm]`、`[embed]`，并把 `[[sources]].path` 改成自己的笔记目录。向量服务必须提供 `/embeddings` 接口；对话与向量服务可以来自不同供应商。

```bash
loci ingest
loci search "部署决策"
loci ask "我们之前决定如何部署？原因是什么？"
```

已经有配置文件？可以用 `python -m pip install loci-rag` 安装，将 `LOCI_HOME` 指向实例目录。需要 PDF、Word 支持时，安装 `python -m pip install 'loci-rag[pdf,docx]'`。

> 密钥也可通过 `BRAIN_LLM_API_KEY`、`BRAIN_EMBED_API_KEY` 环境变量传入。更换向量模型后，需要运行 `loci ingest --force` 重建索引。

## Web 管理台

```bash
loci serve-http
```

打开 **[127.0.0.1:8765/ui](http://127.0.0.1:8765/ui)**，即可浏览 harness 记忆、搜索和提问、编辑共享笔记、执行索引操作并查看审计。界面支持中英文和深浅色切换，无需单独构建前端。

默认情况下，本机回环地址的匿名连接拥有管理员权限。经反向代理或 SSH 隧道访问时，应设置 `[http] local_admin = false` 并配置角色令牌。详见[访问控制说明](docs/guide.zh-CN.md#web-管理台)。

使用 DeepSeek Harness？[loci-dsh](https://github.com/IvenKooLab/loci-dsh) 可以通过同一 HTTP 后端，把搜索、问答和速记放进 Harness 工作台。

## 接入 AI 工具

让各个 MCP 客户端使用**同一个 `LOCI_HOME`**，即可共享配置、索引和记忆文件：

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

如果客户端找不到 `loci-mcp`，请将 `command` 换成可执行文件的绝对路径。实例目录中应有你自己的 `config.toml`。

| MCP 工具 | 用途 |
|---|---|
| `brain_search` · `brain_ask` | 检索片段，或生成带来源的回答 |
| `brain_remember` · `brain_forget` | 写入或撤回长期记忆 |
| `brain_links` · `brain_graph` | 查看笔记链接和提取的知识关系 |
| `brain_wiki` · `brain_harness` | 整理专题知识、查看 Agent 记忆 |
| `brain_stats` · `brain_ingest` | 查看和刷新索引 |

服务还提供笔记资源，以及简报、学习计划和矛盾检查提示词。详细配置见 [MCP 接入指南](docs/guide.zh-CN.md#接入任意-mcp-宿主)。

![loci-mcp — 真实 JSON-RPC 会话](docs/assets/mcp-tools.png)

*真实 `loci-mcp` 的输出：`initialize`、`tools/list`、`prompts/list`。*

### 原生版本（Rust）

同一套检索管线和同一套 MCP 接口，但不需要安装 Python 运行时——单个二进制，索引是一个 SQLite 文件而不是一个数据库目录：

```bash
cargo build --release -p loci-cli     # 在 native/ 下
./target/release/loci-mcp --config ~/.loci/config.toml
./target/release/loci gui             # 同一套控制台，原生提供
```

状态：检索管线、MCP 接口、harness 发现、索引迁移和控制台都已移植；只有 harness 摘要生成仍是 Python 独有。移植了哪些、以及钉住行为的测试见 [`native/`](native/)（分块、冻结的 `default` 分词器、CJK 双字分词器对 decoy 的修复、RRF、增量索引）。

**两个版本的存储格式不同**（SQLite 与 ChromaDB 目录），但数据可以互通：Python 版用 `loci export` 导出，原生版用 `loci import` 导入；若嵌入模型不一致会被拒绝，除非显式加 `--force`。

## 日常怎么用

```bash
loci watch                            # 持续索引发生变化的文档
loci remember "演示使用预发布环境" --title "演示环境约定"
loci search "演示环境" --tag memory
loci ask "准备演示时要注意什么？" --verify
loci harness                          # 查看各个 Agent 的记忆状态
```

索引按文件变化增量更新，记忆始终是可读的 Markdown。跨机器同步时，同步原始文件与记忆笔记，再分别建立本地索引；不要把密钥放进仓库。

<details>
<summary><strong>查看一次终端检索演示</strong></summary>

![loci 终端演示](docs/assets/loci-demo.gif)

[使用指南](docs/guide.zh-CN.md#demo) 保留了原始双语检索示例，以及可以在自己的语料上复跑的小型评估。

</details>

## 文档导航

| 文档 | 内容 |
|---|---|
| [中文使用指南](docs/guide.zh-CN.md) / [English guide](docs/guide.en.md) | 命令、筛选、harness 配置、访问控制和本地模型 |
| [配置示例](config.example.toml) | 模型服务、文档目录和运行参数 |
| [架构说明](docs/ARCHITECTURE.md) | 模块划分与检索流程 |
| [更新记录](CHANGELOG.md) · [路线图](docs/roadmap.md) | 已发布功能与后续计划 |
| [参与贡献](CONTRIBUTING.md) | 开发约定与离线测试 |

运行时使用 OpenAI 兼容 SDK 与 ChromaDB，不依赖 LangChain 或 LlamaIndex。BM25、加载器与 MCP 传输由项目自身实现。

```bash
python -m pip install -e '.[dev,pdf]'
pytest  # 纯离线测试，无需 API key
```

收录与展示：[Glama](https://glama.ai/mcp/servers/IvenKooLab/loci)、[ModelScope](https://modelscope.cn/mcp/servers/IvenKooLab/loci)、[awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers)。源码：[GitHub](https://github.com/IvenKooLab/loci) · [Gitee](https://gitee.com/IvenKooLab/loci)。[MIT 许可证](LICENSE)。
