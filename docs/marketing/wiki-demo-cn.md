# brain_wiki 实测记录（2026-09-10 22:12）
语料：minimax-h3-turing 仓库文档（199 chunks）

生成耗时：115 秒 | 蒸馏来源：12 段 | 入索引：11 chunks

--- 生成的页面内容 ---

---
tags: [wiki, 在-2080ti-上跑-h3-的加速路线有哪些]
topic: 在 2080Ti 上跑 H3 的加速路线有哪些
generated: 2026-09-10 22:14
sources: 12
---
# 在 2080Ti 上跑 H3 的加速路线

2080Ti 22G（Turing 架构，sm_75）在运行 H3 时受限于硬件缺乏 FP8/BF16 张量核心，必须采用特定的量化与工作流配置。目前最优的基准方案是社区维护的 [[compat]] 工作流配合 [[W4A8]] 权重，其 4 步 Turbo 路线的物理极限约为 5.7 分钟/镜。虽然部分加速节点（如 [[SageAttention]]）因架构原因无法使用，但通过 [[T8 BlockCache]] 和 [[PDD LoRA]] 等组合，可在草稿或特定流程下实现显著提速，最高可将耗时压缩至 3 分钟左右。

## 硬件限制与量化路线

由于 Turing 架构缺乏 FP8/BF16 张量核心，激活值降至 4bit 后没有高质量计算路径兜底，导致 [[W4A4]] 量化路线不可用。实测数据显示，W4A4 的重建误差高达 0.2005，画面会出现彩色撕裂；而 [[W4A8]]（权重 4bit + 激活 INT8）的误差仅为 0.0110，画面正常。因此，H3 官方发布的 W4A8 mixed 权重是该卡唯一可用的形态。

## 基础工作流

H3 官方完整版工作流在 Turing 卡上会因节点缺失（如 T8 BlockCache）和模型不匹配而报错。社区维护的 [[compat]] 工作流是降级适配后的最优解，它去除了 sm_75 无法运行的加速节点，并将模型文件对齐至 W4A8 权重，保留了 4 步 Turbo 路线和原生音频功能。

## 可用加速路线

### T8 BlockCache
从 v0.33.1 版本开始可用，但存在复现性问题。
*   **激进档（threshold 1.0）**：在 4 步 Turbo 路线上可提速 43%，耗时约 2.7 分钟/镜。
*   **适用场景**：仅建议用于草稿、预览或选镜头。
*   **限制**：同 seed 不可复现，且默认参数（0.12）在 4 步路线上无效，反而增加缓存开销。成片镜头建议关闭以保证一致性。

### PDD LoRA
一种 8 步加速路线，已实测落地。
*   **独立使用**：耗时约 600s/镜，可复现且画质经过蒸馏。
*   **组合使用**：配合 T8 激进档，耗时可降至 210s（t2v 路线）甚至 192s（i2v 路线），提速约 34%-51%。
*   **优势**：解决了 T8 单独使用时的不可复现问题，适合成片产出。

### RTX VSR
可用于后期超分（640×352 → 1080p），处理速度为 47ms/帧，但不属于生成加速范畴。

## 不可用或排除路线

*   [[SageAttention]]：Triton INT8 内核在 sm_75 上编译失败，CUDA 内核虽能编译但接入管线会崩溃，目前判死。
*   [[TE-Speed]]：虽然能安装运行，但在 4 步 Turbo 这种短步数路线上，其有损压缩会导致语义崩坏，生成画面与提示词脱钩，已被永久排除。

## 性能基准参考

基于 640×352 分辨率、[[W4A8]] 权重的实测耗时：
*   **基线（4 步 Turbo）**：5.7 分钟/镜（物理极限）。
*   **T8 激进档（4 步）**：2.7 分钟/镜（不可复现）。
*   **PDD + T8（8 步）**：约 3.5 分钟/镜（可复现，当前综合最优解）。

## Sources

- E:\work\gitee\minimax-h3-turing\docs\01-hardware-limits.md > 01 · 2080Ti 22G 的先天限制
- E:\work\gitee\minimax-h3-turing\docs\05-workflows.md > 05 · compat 工作流说明 > 为什么是 "compat"
- E:\work\gitee\minimax-h3-turing\docs\06-faq.md > 06 · 踩坑 FAQ > 9. TE-Speed 能装能跑，但作品报废
- E:\work\gitee\minimax-h3-turing\docs\01-hardware-limits.md > 01 · 2080Ti 22G 的先天限制 > 对 H3 的三个直接影响 > 2. DiT 必须跑 INT8（W4A8）
- E:\work\gitee\minimax-h3-turing\docs\08-t8-blockcache-4step.md > 08 · T8 BlockCache 四步实测：43% 提速就在眼前，但有两个坑 > 实操建议（4 步 Turbo 路线）
- E:\work\gitee\minimax-h3-turing\docs\07-upgrade-watch.md > 07 · ComfyUI 升级窗口追踪 > 提速路线判决全景（截至本文）
- E:\work\gitee\minimax-h3-turing\docs\01-hardware-limits.md > 01 · 2080Ti 22G 的先天限制 > h3lite 仓库没有 2080 专属 issue
- E:\work\gitee\minimax-h3-turing\docs\02-w4a8-vs-w4a4.md > 02 · 量化路线实测：W4A8 vs W4A4 > 误差数据
- E:\work\gitee\minimax-h3-turing\docs\09-pdd-backport.md > 09 · PDD 提前落地：不等 release 的 master backport 实录 > Ref2VA（i2v 路线）同样落地（2026-09-04 补测）
- E:\work\gitee\minimax-h3-turing\docs\04-community-tips.md > 04 · 社区经验验证：可直接抄的三点
- E:\work\gitee\minimax-h3-turing\docs\01-hardware-limits.md > 01 · 2080Ti 22G 的先天限制 > 对 H3 的三个直接影响 > 1. SageAttention / T8 加速内核面向 SM80+
- E:\work\gitee\minimax-h3-turing\docs\09-pdd-backport.md > 09 · PDD 提前落地：不等 release 的 master backport 实录 > 未尽事项

