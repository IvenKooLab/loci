# second-brain-rag 🧠

**给散落在十几个目录里的项目文档、笔记、聊天记录，装一个可问答的「第二大脑」。**

本地文档 → 切分 → 向量化 → 检索 → LLM 回答（带引用来源）。纯本地索引，数据不出门；LLM 走任意 OpenAI 兼容 API（智谱 / DeepSeek / Kimi / OpenAI 均可）。

> 为什么不用 LangChain？核心链路只有 300 行，原生实现意味着每个环节可控可改可学。等需要复杂编排时再上框架不迟。

## 架构

```
本地文档目录 (markdown/txt, 递归)
        │  ingest
        ▼
loaders ──► chunker (按标题切 + 滑窗兜底) ──► embedder ──► store (ChromaDB 持久化)
        │  ask
        ▼
retriever (top-k 相似度) ──► answer (LLM 组装回答 + 引用来源)
```

## 快速开始

```bash
pip install -r requirements.txt

# 1. 配置：复制示例并改成你的
cp config.example.toml config.toml
#    填入 API key、模型、以及你要灌进去的文档目录

# 2. 灌数据（增量，按内容 hash 去重，重复跑安全）
python main.py ingest

# 3. 纯检索（看看切分和召回效果）
python main.py search "ComfyAgent 的零依赖是怎么做到的"

# 4. 问答（带引用来源）
python main.py ask "H3 在 2080Ti 上为什么必须用 W4A8"
```

## 配置说明

| 配置项 | 说明 |
|---|---|
| `llm` 段 | base_url / api_key / model —— 任意 OpenAI 兼容端点 |
| `embed` 段 | 同上；模型需为 embedding 类（如 `embedding-3`） |
| `sources` | 文档目录列表，递归扫描 `.md` `.txt` |
| `chunk` | 切分参数（默认 800 字符 / 重叠 100） |
| `top_k` | 检索条数（默认 5） |

## 设计决定

- **ChromaDB 本地持久化**：零服务、零运维，`pip install` 即用；数据量大再换 Milvus
- **增量索引**：文件按内容 hash 记账，改了才重灌，删除自动清理
- **回答必带引用**：每条回答附来源文件路径与切分位置，可溯源、可验证
- **密钥不落码**：key 走 config.toml（已 gitignore）或环境变量

## Roadmap

见 [docs/roadmap.md](docs/roadmap.md) —— MCP server、Web UI、混合检索、rerank、图片索引。

## License

MIT
