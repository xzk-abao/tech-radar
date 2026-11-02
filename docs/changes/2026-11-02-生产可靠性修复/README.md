# 2026-11-02 生产可靠性修复（carry-forward 缓存 + stale 源）

- **状态**：已完成本地验证；线上待后续 Actions 定时任务验证（首次运行写入新 cache，第二次起 carry-forward 可用）
- **需求来源**：2026-11-02 项目分析发现的两个 P1：生产 carry-forward 实际失效、MCP Releases 停滞但健康页显示 ok
- **涉及端**：GitHub Actions 缓存 + 采集健康判定 + 前端健康页 + 测试
- **完成时间**：2026-11-02

## 背景与目标

项目已经稳定运行，但“源健康”和“失败源缓存续用”两个对外承诺在生产环境存在偏差：

1. `carry_forward_failed_sources` 从 `data/items.json` 读取上一轮数据，但 Actions 缓存没有持久化这个文件，导致线上源失败时仍然丢条目。
2. MCP Releases 上游最新 release 停留在 2026-07-28，30 天窗口内没有条目，但健康页仍显示 `ok / items=9`，与 JavaGuide 死源是同一种模式。

目标：让 carry-forward 在生产真正生效；把“可抓取但长期无窗口内条目”的源标记为 `stale`，不再计入 `sources_ok`；保持 MCP 源启用，便于上游恢复后自动重新产出。

## 根因与证据

### 1. carry-forward 失效

代码链路：

- `radar/store.py:176`：`carry_forward_failed_sources()` 用 `read_dataset(data_dir)` 读取 `data/items.json`。
- 修复前的 `.github/workflows/radar.yml` 缓存步骤只缓存 `data/state` 和 `data/history`；修复后见改动表。
- `.gitignore:8`：整个 `data/` 被忽略，`git ls-files data` 为空。
- runner 每次都是全新 checkout，`data/items.json` 不存在，`read_dataset()` 返回空，`carried` 恒为 0。

结论：README 中“上一轮条目缓存续用”只在本地存在 `data/items.json` 时成立，线上不成立。

### 2. MCP Releases 停滞

GitHub Releases 页面（<https://github.com/modelcontextprotocol/modelcontextprotocol/releases>）最新 release：

```text
2026-07-28
```

线上快照（`generated_at=2026-11-01T21:54:58Z`）：

- MCP Releases health：`status=ok`、`items=9`、`last_item_at=2026-07-28T16:48:26Z`
- 最终 `data/items.json` 中 `mcp_releases` 条目：**0**
- 原因：`window_hours=720`（30 天）把 9 条全部过滤掉

结论：抓取成功不等于有有效产出；健康状态需要区分“抓取成功”和“窗口内有产出”。

## 改动内容

| 模块 | 文件:行号 | 内容 |
|---|---|---|
| 缓存 | `.github/workflows/radar.yml:43-52` | Actions cache 增加 `data/items.json`，保证下一轮 carry-forward 有上一轮数据 |
| 健康判定 | `radar/fetch.py:76-86` | 新增 `_mark_stale_if_needed()`：源抓取成功但最新条目早于窗口时，状态改为 `stale` |
| 采集入口 | `radar/fetch.py:146`、`:217`、`:274` | `fetch_feed`、GitHub Search、GitHub Watchlist 调用 stale 判定 |
| 统计 | `radar/store.py:45-56` | `sources_ok` 不再包含 `stale`；新增 `sources_stale` |
| CLI | `radar/cli.py:80-81` | 健康摘要增加 stale 数量 |
| 前端 | `web/app.js:137-144`、`:315` | 有 stale 源时健康 pill 显示 warn/tooltip；stale 说明文字用 amber |
| 前端 | `web/styles.css:384`、`:388` | 新增 `.status.stale` 与 `.err-text.stale` 样式 |
| 前端 | `web/index.html:87`、`:91` | 健康页说明补充 `stale` 语义；表头改为“错误 / 说明” |
| 测试 | `tests/test_fetch.py` | 覆盖 stale 判定、非 stale、error/baseline 不被覆盖、真实 feed 入口 |
| 测试 | `tests/test_store.py` | 覆盖 `sources_ok` 排除 stale、`sources_stale` 计数 |
| 测试 | `tests/test_workflow.py` | 锁定 Actions cache 必须包含 `data/items.json` |
| 文档 | `README.md` | 源清单说明、已知限制、验证记录 |

## 设计要点 / 关键决策

1. **缓存 `data/items.json` 而不是整个 `data/`**：只增加 carry-forward 需要的最小文件，避免把 history 之外的新文件意外带进缓存。
2. **stale 是独立状态，不归入 error**：源本身可访问，只是没有窗口内内容；归入 error 会制造告警噪音，归入 ok 会掩盖停更。
3. **stale 不计入 `sources_ok`**：健康 headline 更接近“可用产出”，而不是“HTTP 成功”。
4. **MCP 保持启用**：没有找到同等级替代源；保留配置并标记 stale，上游恢复发版后会自动恢复，不需要再次改配置。
5. **使用全局 `window_hours` 判定 stale**：当前只有 30 天窗口；如果未来出现低频但正常的源，再考虑 per-source `stale_after_hours`。
6. **首次上线有一个空窗期**：旧 cache 不含 `data/items.json`，改动后的第一次运行只会在结束时写入新 cache；从第二次运行开始，carry-forward 才真正可用。

## 验证

| 验证项 | 结果 |
|---|---|
| 单元测试 | `python -m pytest -q` → **32 passed** |
| stale 判定 | 60 天前条目的源 → `stale`；4 小时前条目 → `ok` |
| 状态保护 | 已是 `error`/`baseline` 的源不会被 stale 覆盖 |
| feed 入口 | 伪造 2026-07-01 的 Atom → `fetch_feed` 返回 `stale` |
| 统计 | `sources_ok` 只统计 ok/baseline；`sources_stale` 单独计数 |
| workflow 配置 | `tests/test_workflow.py` 锁定 cache 步骤包含 `data/items.json` |
| 真实上游数据 | GitHub API 取 MCP 3 条 releases，调用 `_mark_stale_if_needed()` → `status=stale`，note 为 `no items within 720h window; latest 2026-07-28T16:47:49+00:00` |
| 最近源完整跑通 | `python -m radar run --only inside_java,spring_blog --no-llm`（临时目录）→ 14 条、2/2 ok、0 stale，静态站构建成功 |
| 线上 | 待后续 Actions 定时任务验证：第一次运行写入含 `data/items.json` 的新 cache，第二次起 carry-forward 可用；本地 `python -m radar check --only mcp_releases` 因本机访问 `github.com` 超时失败，属于已知网络限制，不是代码失败 |
| 上游事实 | GitHub Releases 页面实测最新 release 为 2026-07-28 |

复现命令：

```bash
cd D:\projects\tech-radar
python -m pytest -q
python -m radar check --only inside_java,spring_blog
```

## 复发处理

1. **线上 carry-forward 又失效**：先确认 Actions cache 是否命中、`data/items.json` 是否在缓存路径；再看 `carry_forward_failed_sources` 是否读到上一轮 dataset。
2. **健康页出现新的 stale 源**：看该源的 `last_item_at`；如果确实停更，按 JavaGuide 的先例禁用或替换；如果是低频正常源，再评估 per-source stale 阈值。
3. **stale 误报**：确认源的 `timezone_offset_hours` 和发布时间是否正确；如果源本身低频但正常，调整 `window_hours` 或新增 `stale_after_hours` 配置。
4. **新增源**：继续按 README 的五维质量审核，并用 `python -m radar check` 验证可抓取。

## 相关资料

- 线上数据：<https://xzk-abao.github.io/tech-radar/data/items.json>
- 最近一次 Actions run：<https://github.com/xzk-abao/tech-radar/actions/runs/41354391714>
- MCP Releases：<https://github.com/modelcontextprotocol/modelcontextprotocol/releases>
- workflow：`../../../.github/workflows/radar.yml`
- 测试：`../../../tests/test_fetch.py`、`../../../tests/test_store.py`、`../../../tests/test_workflow.py`
- 上一版归档：`../2026-11-01-数据源质量修复/`
