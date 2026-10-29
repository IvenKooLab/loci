# 将 Obsidian 笔记接入 loci（Python 版）

这份指南针对本源码版本的 Python 实现。Obsidian 继续编辑原始 Markdown；loci 建立独立的检索索引，并通过 MCP 将带文件和章节的段落提供给 AI。接入前备份笔记，并先用不含敏感信息的小型测试库验证。

**选择资料范围：**扫描会递归读取配置目录下支持的文件，包括 `.obsidian` 内的 Markdown、其他隐藏目录和部分指向文件的符号链接；不会继承 Obsidian 的排除设置。嵌入服务会收到被索引的文本，问答服务会收到问题与检索段落。先核查文件、服务地址和隐私要求；不想发送的内容不要放进来源目录。若 vault 包含不应索引的内容，请使用单独的、经过筛选的笔记副本或只配置安全子目录。loci 索引与 Obsidian 库分开保存。

## 1. 安装并创建独立实例

需要 Python 3.11+。从本仓库根目录执行：

```bash
python -m pip install -e .
mkdir -p "$HOME/loci-obsidian"
cp config.example.toml "$HOME/loci-obsidian/config.toml"
export LOCI_HOME="$HOME/loci-obsidian"
```

Windows 可在 PowerShell 中设置 `$env:LOCI_HOME = 'C:/Users/你的用户名/loci-obsidian'`，并将示例配置复制到该目录。编辑 `config.toml` 中的原有项，不要重复创建 TOML 表：

```toml
[llm]
base_url = "https://your-chat-provider.example/v1"
api_key = ""
model = "your-chat-model"

[embed]
base_url = "https://your-embedding-provider.example/v1"
api_key = ""
model = "your-embedding-model"

[[sources]]
path = "/absolute/path/to/your/filtered-vault"

[bm25]
tokenizer = "cjk_bigram" # 中文笔记可选；英文也可用默认值
```

把示例配置中已有的 `[[sources]]` 路径改成实际目录，删除或注释不需要的示例来源。Windows TOML 路径可使用正斜杠，如 `C:/Users/name/Notes`。对话和向量端点须分别兼容 OpenAI 的聊天和 `/embeddings` 接口；模型名称与密钥由服务商提供。可使用本地兼容服务，不必使用云服务。

在运行 loci **和启动 MCP 客户端的环境**中设置 `BRAIN_LLM_API_KEY` 和 `BRAIN_EMBED_API_KEY`，或者通过客户端的安全环境变量配置；不要将密钥提交到仓库。服务是否要求密钥取决于服务商，loci 的 Python 配置校验要求两个值非空。不同模型或提供商的向量不应混用；更换向量模型时备份索引并运行 `loci ingest --force`。

## 2. 建索引并核对证据

```bash
loci ingest
loci stats
loci search "笔记里一个明确的关键词"
loci ask "这个决定是什么？请引用文件和章节。"
```

确认 `loci search` 的路径、章节与原文一致。首次索引后修改笔记，再运行 `loci ingest` 更新；来源目录不可用时当前版本会停止索引，保留已有索引。正常存在的目录中删除的文件会在下次索引时从索引移除。请勿将此检查当作检测所有磁盘、读取错误或同步故障的保证；应定期备份原始库和索引。

`loci ask --verify "问题"` 可以请求额外的模型核查，但核查仍由模型完成。模型可能遗漏、编造或误用引用；应以 `loci search` 返回的原文、文件及章节为准，不能把引用格式本身当成真实性证明。

## 3. 连接 AI 客户端

在支持 MCP 的客户端中添加（字段位置取决于客户端）：

```json
{
  "mcpServers": {
    "loci": {
      "command": "/absolute/path/to/loci-mcp",
      "env": { "LOCI_HOME": "/absolute/path/to/loci-obsidian" }
    }
  }
}
```

使用 `which loci-mcp`（Windows PowerShell 用 `Get-Command loci-mcp`）找可执行文件的绝对路径；在客户端的安全配置中为该进程提供上述环境变量。重启客户端后，让 AI 使用 `brain_search` 查找一个你知道答案的笔记，并要求它引用返回的路径、章节和原文；也可调用 `brain_ask`。如果工具不可用，先检查执行路径、`LOCI_HOME`、密钥和 `loci ingest`。不同客户端不会自动调用工具，是否调用由客户端及其权限设置决定。

## 当前能力边界

| 内容 | Python | Rust 原生版（当前源码） |
|---|---|---|
| Markdown 与标题章节 | 支持；索引 frontmatter 后的正文 | 支持；使用独立 SQLite 索引 |
| frontmatter 标签 | 支持简单标量、行内列表和多行列表，不是完整 YAML | 支持简单标量及行内列表；多行标签列表不保证 |
| `[[链接]]` | 记录链接目标；`![[嵌入]]` 不作为链接，也不展开被引用内容 | 解析链接的行为不同，嵌入不展开 |
| 附件 | PDF/DOCX 等需对应可选依赖；图片 OCR 需 `[ocr]` | Markdown、文本、HTML、org 以文本方式读取；PDF/DOCX/OCR 尚不支持 |
| MCP | `brain_search`、`brain_ask` 等 | `brain_search`、`brain_stats`、`brain_ingest`、`brain_harness`；没有 `brain_ask` |
| 问答 | CLI/MCP/Web 可使用配置的模型 | Web 控制台有问答；CLI 与 MCP 没有对应 ask 命令 |
| 索引互通 | ChromaDB；通过 export/import 交换 | SQLite；通过 export/import 交换，不直接共享数据库 |

别名、块引用、嵌入展开、复杂 YAML、插件生成内容和任意 Obsidian 语法并不保证完整语义兼容。请用自己的脱敏笔记验证；文档格式能被读取不代表所有内容都被正确解析。参见 [原生版说明](../native/README.md)。

## 重跑离线评测

从源码仓库执行 `python scripts/eval_obsidian.py`。它在临时目录使用虚构 vault、确定性测试向量和实际 Python 检索器，报告正确文件、章节及原文的 hit@1 和 hit@5；不访问真实 vault 或模型。样本很小，只用于回归，不能推断真实用户的召回率、语义能力或模型回答正确率。
