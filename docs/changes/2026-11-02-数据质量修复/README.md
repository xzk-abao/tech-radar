# 2026-11-02 数据质量修复（同源误合并 + 有效条目口径）

- **状态**：已完成本地验证；线上待后续 Actions 运行验证
- **需求来源**：2026-11-02 项目分析发现的 P2：同站去重误合并、健康页只显示原始条数
- **涉及端**：去重聚类 + 健康统计 + 前端健康页 + 测试
- **完成时间**：2026-11-02

## 背景与目标

线上快照（`generated_at=2026-11-01T21:54:58Z`）有 8 个多成员簇，其中 6 个是真正的跨源同事件，2 个是同源误合并：

- Baeldung 的 `Java Weekly, Issue 667/668/669` 被合成 1 条；
- GitHub Changelog 的 3 篇不同 Copilot 文章被合成 1 条。

同时，健康页的“条目”是 feed 原始条数，无法看出时间窗口和去重后实际进入页面的数量。例如线上 HelloGitHub 原始 20 条、最终 1 条；GitHub Watchlist 原始 24 条、最终 11 条。

目标：

1. 同源系列文章（Issue 编号、相似标题）不再被误合并；
2. 跨源同事件仍然正常合并；
3. 健康页同时显示原始条数和有效条数，headline 增加“有产出源”覆盖。

## 根因与证据

### 1. 同源误合并

`radar/dedupe.py` 的 same-host 规则：

```python
if a_host and a_host == b_host and similarity >= 0.45:
    return True
```

它对“同一个 feed 内的不同文章”也生效。Baeldung Issue 669 与 668 的 token 相似度约 0.6，低于通用阈值 0.62，但满足 same-host 0.45，于是被合并。GitHub Changelog 的三篇 Copilot 文章同样满足同站 0.45。

`extract_versions` 只识别带点版本号（如 `2.1.316`），识别不了 `Issue 669` 这类序号。

### 2. 健康页口径

`radar/fetch.py` 的 `health.items` 是 feed 原始条数；`filter_window` 和 `cluster_items` 之后，很多条目会被窗口过滤或成为 cluster member，但健康记录没有更新。线上示例：

| 源 | health.items | 最终条目 |
|---|---:|---:|
| HelloGitHub | 20 | 1 |
| GitHub Watchlist | 24 | 11 |
| Baeldung | 12 | 6 |
| MCP Releases | 9 | 0 |

## 改动内容

| 模块 | 文件:行号 | 内容 |
|---|---|---|
| 序号识别 | `radar/util.py:129` | 新增 `extract_serials()`：识别 `Issue 669`、`No. 42`、`#123`、`第 669 期` |
| 去重 | `radar/dedupe.py:21-24` | 双方都有序号且不同 → 不合并；保护 Issue/期号 |
| 去重 | `radar/dedupe.py:34-36` | same-host 0.45 放宽规则要求 `source_id` 不同，避免同源误合并 |
| 模型 | `radar/models.py:51` | `SourceHealth` 增加 `effective_items` |
| 统计 | `radar/store.py:71-73` | 按最终 primaries 计算每个源的 `effective_items` |
| 统计 | `radar/store.py:54` | 新增 `sources_with_items` |
| CLI | `radar/cli.py:80-82` | 健康摘要增加 `with items` |
| demo | `radar/cli.py:163-171` | demo 只统计启用源，并用 demo 主条目数回填原始条数 |
| 前端 | `web/app.js:115-116` | 概览增加“X/Y 源有产出” |
| 前端 | `web/app.js:143-147` | 健康 pill tooltip 增加有产出源数量 |
| 前端 | `web/app.js:177` | cluster 标签按来源数显示“多源”或“同事件” |
| 前端 | `web/app.js:318-322` | 健康表显示原始条数 + 有效条数 |
| 前端 | `web/index.html:91` | 表头改为“条目 / 有效” |
| 测试 | `tests/test_util.py` | `extract_serials` 覆盖中英文序号 |
| 测试 | `tests/test_dedupe.py` | 同源 Issue/Changelog 不合并；跨源同标题仍合并 |
| 测试 | `tests/test_store.py` | `effective_items` 与 `sources_with_items` 口径 |
| 测试 | `tests/test_cli.py` | demo 只统计启用源，有效条数与主条目一致 |

## 设计要点 / 关键决策

1. **序号保护放在相似度之前**：只要双方都带序号且不同，就判定为不同事件，避免“Issue 669/668”因标题太像而合并。
2. **same-host 放宽只用于跨源**：同源内容重复通常 URL 相同；same-host 0.45 主要是为了跨源转载/改标题，不应该在单个 feed 内生效。
3. **保留 0.62 通用相似度规则**：跨源同标题仍然合并；现有测试和线上 GPT-6.1 Terra（OpenAI + Simon Willison）验证通过。当前同源误合并案例都低于 0.62；如果后续出现同源高相似误合并，再把 0.62 也限制为跨源。
4. **有效条数按最终 primaries 统计**：cluster member 不再单独计数；这是保守口径，避免健康页高估。
5. **`items` 与 `effective_items` 都保留**：原始条数用于判断源是否还在产出，有效条数用于判断实际贡献。

## 验证

| 验证项 | 结果 |
|---|---|
| 单元测试 | `python -m pytest -q` → **38 passed** |
| 同源 Issue | Baeldung Issue 669/668 保持 2 个簇 |
| 同源 Changelog | 3 篇 Copilot 文章保持 3 个簇 |
| 跨源同事件 | OpenAI + Simon Willison 的 GPT-6.1 Terra 仍合并为 1 簇 |
| 真实采集 | `python -m radar run --only baeldung,github_changelog --no-llm`（临时目录）→ 18 条、18 簇、0 多成员簇；Baeldung 原始 12 → 有效 8，Changelog 原始 10 → 有效 10 |
| 跨源真实采集 | `python -m radar run --only openai_news,simon_willison --no-llm` → 39 条；GPT-6.1 Terra 合并为 1 簇（2 个来源） |
| demo 回归 | demo 只统计启用源（19），`sources_with_items` 与 demo 主条目数一致 |
| 线上 | 待后续 Actions 运行验证；当前线上仍是修复前数据 |

复现命令：

```bash
cd D:\projects\tech-radar
python -m pytest -q
python -m radar run --only baeldung,github_changelog --no-llm --out <tmp>/data --public <tmp>/public
```

## 复发处理

1. **同源文章又被合并**：先看 `radar/dedupe.py` 的 same-host 条件和 `extract_serials` 是否覆盖该源的编号格式；补充正则和测试。
2. **跨源同事件没有合并**：检查标题相似度是否低于 0.62、是否被不同的序号/版本号保护误判；看 `members` 是否为空。
3. **健康页有效条数异常低**：对比 `items` 与 `effective_items`；如果原始有量但有效为 0，优先查时间窗口、序号保护、same-host 规则。
4. **新增源**：用 `python -m radar check` 看原始条数，再跑一次 `run` 看 `effective_items`，确认源的实际贡献。

## 相关资料

- 线上数据：<https://xzk-abao.github.io/tech-radar/data/items.json>
- 去重实现：`../../../radar/dedupe.py`
- 时间/序号工具：`../../../radar/util.py`
- 测试：`../../../tests/test_dedupe.py`、`../../../tests/test_store.py`
- 上一版归档：`../2026-11-02-生产可靠性修复/`
