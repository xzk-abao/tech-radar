# 2026-11-01 数据源质量修复（JavaGuide 死源 + InfoQ 时区）

- **状态**：已上线
- **需求来源**：技术雷达上线后复盘发现的源质量问题；P1 数据质量修复
- **涉及端**：采集配置 `config/sources.json` + feed 时间归一化 `radar/fetch.py` + 单元测试
- **完成时间**：2026-11-01

## 背景与目标

首次部署 GitHub Pages 后，线上数据暴露两个源质量问题：

1. **JavaGuide 实际已停更**：健康检查显示 ok，但最终 0 条，导致配置里有一个“看起来正常、实际没有产出”的源。
2. **InfoQ 时间戳整体晚 8 小时**：线上出现 5 条发布时间在未来的条目，`recency` 被钳到满分，排名虚高。

目标：去掉死源、修正时间偏移，并加测试防止回退；不改变评分权重和页面结构。

## 根因与证据

### JavaGuide 死源

直接抓取 `https://javaguide.cn/rss.xml`：

- HTTP 200，返回 100 条
- 最新一条：`Sun, 16 Aug 2026 00:16:35 GMT`
- 当前时间 2026-11-01，最新内容已超过 30 天窗口，`filter_window` 后必然为 0 条

结论：不是抓取失败，而是源本身停更；健康状态 ok 会误导判断。

### InfoQ 时区偏移

直接抓取 `https://www.infoq.cn/feed`，最新一条原始时间：

```
Sun, 01 Nov 2026 14:00:00 GMT
```

该时间实际是北京时间（UTC+8），但 feed 标成了 GMT。`feedparser` 按 GMT 解析，得到 14:00Z；真实时间应为 06:00Z，因此固定晚 8 小时。

修复前线上快照（`generated_at=2026-11-01T11:26:37Z`）中有 **5 条 InfoQ 未来时间条目**，最多比运行时间晚 **7.8 小时**。`recency_score` 对负 age 做 `max(0.0, ...)`，这些条目会拿到满分 recency。

## 改动内容

| 模块 | 文件:行号 | 内容 |
|---|---|---|
| 时间归一化 | `radar/fetch.py:62` | `_entry_datetime(entry, source)` 支持 `timezone_offset_hours`，按小时修正 feed 时间 |
| feed 入口 | `radar/fetch.py:93` | `_feed_item` 调用时传入 source 配置 |
| 源配置 | `config/sources.json:261` | JavaGuide `enabled: false`（保留配置便于恢复） |
| 源配置 | `config/sources.json:274` | 新增 `inside_java`（`https://inside.java/feed.xml`，weight 5） |
| 源配置 | `config/sources.json:298` | InfoQ `timezone_offset_hours: -8` |
| 测试 | `tests/test_fetch.py` | 新增 3 个用例：偏移生效、默认 UTC、质量修复配置状态 |
| 文档 | `README.md` | 源清单、`timezone_offset_hours` 说明、已知限制与验证记录 |

## 设计要点 / 关键决策

1. **偏移放在解析层，而不是评分层**：源头时间错了就应在 ingestion 修正；评分层再补丁会让历史数据继续错误。
2. **JavaGuide 用 `enabled: false` 而不是删除**：保留配置可审计，后续源恢复时改回 true 即可；README 写明停更事实。
3. **JavaGuide 的替代选 Inside Java**：Oracle Java 团队博客，实测 200、10 条、最新 2026-10-30，内容聚焦 JDK/JVM，符合 README 的权威性/信噪比/学习价值标准。
4. **没有加通用“未来时间”惩罚**：先修正已知源；如果未来其他源也出现时间漂移，再考虑通用 guard。当前测试能防止 InfoQ 配置回退。

## 验证

| 验证项 | 结果 |
|---|---|
| 单元测试 | `python -m pytest -q` → **26 passed** |
| InfoQ 本地抓取 | 20 条，未来时间 **0**（修复前 5 条） |
| Inside Java 本地抓取 | 10 条，最新 2026-10-30T00:00:00Z |
| JavaGuide | `enabled=false`，采集跳过 |
| 生产 workflow | [41312056932](https://github.com/xzk-abao/tech-radar/actions/runs/41312056932) → **success** |
| 线上数据 | `generated_at=2026-11-01T13:36:32Z`：**165 条**，26 张知识卡片，official 56 / github 43 / learning 66 |
| 线上源健康 | **19/19 ok，0 error**；Inside Java 10 条，JavaGuide 0 条 |
| 线上未来时间 | **0 条**（修复前 5 条，最多 +7.8h） |
| LLM | calls=1，hits=28，fallbacks=135，errors=[] |

复现命令：

```bash
cd D:\projects\tech-radar
python -m pytest -q
python -m radar check
```

## 复发处理

1. **再次出现未来时间条目**：抓取该源原始 feed，对比 `published` 字符串与实际时区；如是源标错时区，在 `config/sources.json` 加/改 `timezone_offset_hours`，并在 `tests/test_fetch.py` 锁定。
2. **源显示 ok 但长期 0 条**：看 `health.last_item_at`；若早于当前窗口，按死源处理（禁用或替换），不要只看 status。
3. **新增源前的质量审核**：按 README 的五维评分（权威性/信噪比/稳定性/学习价值/时效性），并用 `python -m radar check` 验证可抓取。

## 相关资料

- 部署归档：`../2026-11-01-技术雷达部署上线/`
- 源清单：`../../../config/sources.json`
- 测试：`../../../tests/test_fetch.py`
- 线上地址：<https://xzk-abao.github.io/tech-radar/>
