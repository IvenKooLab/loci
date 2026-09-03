# Roadmap

## v0.1（当前）MVP

- [x] 目录递归扫描 + markdown 标题感知切分
- [x] OpenAI 兼容 embedding / chat（智谱/DeepSeek/Kimi 通吃）
- [x] ChromaDB 本地持久化 + 内容 hash 增量索引
- [x] CLI：ingest / search / ask（回答带引用）

## v0.2 体验补全

- [ ] 文件监听（watchdog）自动增量
- [ ] 混合检索：向量 + BM25 关键词
- [ ] rerank（免费期用 LLM 重排，之后换 bge-reranker 本地）
- [ ] PDF / docx 加载
- [ ] 会话式追问（多轮对话记忆）

## v0.3 生态

- [ ] **MCP server**：把第二大脑接进 ComfyAgent 助手和任意 MCP 宿主
- [ ] Web UI（单文件本地页面，风格对齐 ComfyAgent）
- [ ] 知识图谱模式（Neo4j，GraphRAG 实验）

## 一直不做

- 云端存储（数据出门违背项目初衷）
- 多用户（这是我的第二大脑，不是你的）
