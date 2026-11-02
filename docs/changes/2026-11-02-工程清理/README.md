# 2026-11-02 工程清理（PR CI、去重口径、时区、依赖）

- **状态**：已完成本地验证
- **需求来源**：PR #1 评审后遗留的低优先级清理项
- **涉及端**：GitHub Actions CI + 数据统计 + 历史快照 + 依赖
- **完成时间**：2026-11-02

## 背景与目标

PR #1 上线后遗留四类工程问题：

1. workflow 没有 `pull_request` 触发，PR 不跑 CI；
2. `stats.clusters` 恒等于 `total_items`（只存 primary），页面上“166 条目 / 166 个事件簇”看不出去重效果；
3. history 快照用 UTC 日期，而页面/导出用 `Asia/Shanghai`，凌晨运行会把快照记到前一个本地日期；
4. 存在未使用 import，依赖只有 `>=` 下限。

目标：PR 有 CI 但不会误部署；去重效果可见；历史日期与展示口径一致；依赖可复现。

## 改动内容

| 模块 | 文件:行号 | 内容 |
|---|---|---|
| CI 触发 | `.github/workflows/radar.yml:10-11` | 新增 `pull_request: branches: [main]` |
| CI 安全 | `.github/workflows/radar.yml:63`、`:69` | upload-pages-artifact 与 deploy job 加 `if: github.event_name != 'pull_request'`，PR 只跑测试不部署 |
| 并发 | `.github/workflows/radar.yml:20` | concurrency group 改为 `tech-radar-${{ github.ref }}`，PR 运行不会取消 main 部署 |
| 去重口径 | `radar/store.py:45-55` | `_dataset_stats` 新增 `raw_items` / `deduped`（raw − primaries） |
| 去重口径 | `radar/store.py:77`、`:93` | `write_dataset` 接受 `raw_items`；CLI 传入窗口过滤后的条目数 |
| 去重口径 | `radar/cli.py:79` | 运行摘要改为 `N raw -> M items` |
| 去重口径 | `web/app.js:128-132` | 概览在 deduped > 0 时显示“X 原始 → Y 事件簇” |
| 时区 | `radar/util.py:47-57` | 新增 `local_date(tz_name, now)`，未知时区回退 UTC |
| 时区 | `radar/store.py:100`、`:137-138` | history 快照与 180 天清理 cutoff 均按配置时区取日期 |
| 时区 | `radar/export.py:120` | 导出日期复用 `local_date`，删除重复的 ZoneInfo 逻辑 |
| import | `radar/fetch.py`、`radar/cli.py`、`radar/store.py` | 移除未使用的 `json` / `utcnow` / `datetime` |
| 依赖 | `requirements.txt`、`requirements-dev.txt` | 锁定 `feedparser==6.0.14`、`requests==2.33.0`、`beautifulsoup4==4.15.0`、`pytest==9.1.1` |
| 许可证 | `LICENSE`、`README.md` | 新增 MIT License，README 增加 License 章节 |
| 测试 | `tests/test_workflow.py` | 锁定 PR 触发、PR 跳过部署、per-ref 并发 |
| 测试 | `tests/test_store.py` | 锁定 raw_items/deduped 口径与时区化 history 日期 |
| 测试 | `tests/test_util.py` | 锁定 `local_date` 转换与未知时区回退 |

## 设计要点 / 关键决策

1. **PR 跑完整采集但不部署**：pytest 步骤之外，`radar run` 在 PR 上也会执行，能端到端验证采集链路；upload 与 deploy 被 event guard 跳过，不会把 PR 内容发布到 Pages。
2. **PR 会消耗 LLM 调用**：build job 注入 `DEEPSEEK_API_KEY`，PR 运行最多分析 30 条；个人项目频率低，成本可接受。若以后 PR 频繁，可在 PR 事件上加 `--no-llm`。
3. **concurrency 按 ref 隔离**：`github.ref` 对 PR 是 `refs/pull/N/merge`，对 main 是 `refs/heads/main`，保持 main 内“取消旧部署”的行为不变。
4. **`deduped = raw − primaries`**：primary 即事件簇代表，差值就是被合并进其他簇的重复条目数。
5. **时区统一走 `local_date`**：store、export 共用一个实现；`ZoneInfo` 失败回退 UTC，与原 export 行为一致。

## 验证

| 验证项 | 结果 |
|---|---|
| 单元测试 | `python -m pytest -q` → **56 passed** |
| 去重口径 | demo 12 raw → deduped 1 → 11 items；UI 将显示“12 原始 → 11 事件簇” |
| 两源实跑 | `14 raw -> 14 items`，构建成功 |
| 时区 | 固定 2026-11-01T20:00Z 在 Asia/Shanghai 下 history 记为 `2026-11-02.json` |
| 依赖 | 本地按锁定版本通过全部测试；CI 安装同版本 |
| 前端 | `node --check web/app.js` 通过 |

复现命令：

```bash
cd D:\projects\tech-radar
python -m pytest -q
python -m radar demo --out <tmp>/data --public <tmp>/public
```

## 复发处理

1. **PR 误触发部署**：检查 upload/deploy 的 `if: github.event_name != 'pull_request'` 是否还在（`tests/test_workflow.py` 会拦截）。
2. **PR 互相取消部署**：确认 concurrency group 仍使用 `${{ github.ref }}`。
3. **history 出现 UTC 日期文件**：确认 `write_dataset` 走 `local_date(tz_name)`；旧 UTC 日期文件会被 180 天清理自然淘汰。
4. **依赖升级**：改 `requirements*.txt` 后跑 `python -m pytest -q`，并观察一轮生产 workflow。

## 相关资料

- 上一版归档：`../2026-11-02-健壮性修复/`
- workflow：`../../../.github/workflows/radar.yml`
- 测试：`../../../tests/test_workflow.py`、`../../../tests/test_store.py`
