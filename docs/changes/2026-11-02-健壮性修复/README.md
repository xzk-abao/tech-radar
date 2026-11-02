# 2026-11-02 健壮性修复（重试、未来时间、LLM cache、前端校验）

- **状态**：已完成本地验证；线上待后续 Actions 运行验证
- **需求来源**：2026-11-02 项目分析剩余的 P2/P3：抓取无重试、未来时间缺少通用防护、LLM cache 不区分模型、前端深链/URL 未校验
- **涉及端**：采集重试 + 评分 + LLM 缓存 + 前端
- **完成时间**：2026-11-02

## 背景与目标

前几轮修复解决了 carry-forward、stale 源、同源去重和有效条目口径。剩余的健壮性问题：

1. `_get` 对首次超时/429/5xx 直接判 error，没有重试；
2. `recency_score` 把未来时间钳到 0，InfoQ 之外的新源若标错时区仍会拿到满分 recency；
3. LLM cache key 不包含 provider/model，换模型会复用旧摘要；JSON 解析失败静默 fallback；
4. 前端初始 tab 未校验，`?tab=bogus` 会导致没有 tab 高亮；`href` 未限制协议。

目标：不改变页面结构；在失败路径上更稳、更可观测，并让异常时间/链接有明确标记。

## 根因与证据

### 1. 抓取无重试

`radar/fetch.py` 原 `_get()` 首次 `requests` 异常或 HTTP >= 400 直接返回 error。网络抖动会直接让源进入 error，依赖 carry-forward 兜底；而 carry-forward 之前在生产环境失效（已在 `../2026-11-02-生产可靠性修复/` 修复）。

### 2. 未来时间

`radar/score.py` 的 `recency_score()` 使用 `max(0.0, age)`，未来时间 age 为负，直接被钳到 0，recency 满分。InfoQ 已通过 `timezone_offset_hours: -8` 修正，但其他新源没有通用保护。

### 3. LLM cache

`radar/summarize.py` 原 cache key 只有 `PROMPT_VERSION + title + url`。从 DeepSeek 换到方舟或换模型时，会命中旧模型生成的摘要；JSON 解析失败返回 `[]`，不写入 `stats["errors"]`，看起来像正常降级。

### 4. 前端

- `init()` 直接使用 `?tab=` / `#` 的值，未校验 allowed tabs；
- `href="${esc(item.url)}"` 只做 HTML 转义，没有协议白名单，`javascript:` 链接可被点击。

## 改动内容

| 模块 | 文件:行号 | 内容 |
|---|---|---|
| 重试 | `radar/fetch.py:49-85` | `_get()` 支持 attempts/backoff；仅对超时、429、5xx 重试；429 参考 `Retry-After`；404/403 不重试 |
| 重试入口 | `radar/fetch.py:87-99` | 新增 `_get_for_source()`，从 settings 读取 retry 配置 |
| 时间归一化 | `radar/fetch.py:117-129` | 新增 `_normalize_future()`：超过 `future_tolerance_hours` 的条目 clamp 到当前时间，保留原始时间 |
| 健康提示 | `radar/fetch.py:131-136` | `_note_future_items()` 在健康页记录 “future-dated item(s) clamped” |
| 评分 | `radar/score.py:63-66` | future_timestamp 条目的 recency 乘以 0.3，避免异常时间排在顶部 |
| LLM cache | `radar/summarize.py:30-34` | cache key 增加 provider/model；换模型自动失效 |
| LLM 错误统计 | `radar/summarize.py:191-197` | 无有效 JSON 或返回行数不足时写入 `stats["errors"]` |
| 前端 tab | `web/app.js:18`、`:366`、`:427-428` | 统一 allowed tabs；非法 `?tab=` 回退到 all |
| 前端 URL | `web/app.js:29-36` | 新增 `safeUrl()`，只允许 http/https |
| 前端链接 | `web/app.js:193`、`:217`、`:276`、`:296` | 所有外链改用 `safeUrl()` |
| 前端标记 | `web/app.js:208` | future_timestamp 条目显示“时间异常”badge |
| 配置 | `config/sources.json` | 新增 `retry_attempts`、`retry_backoff_seconds`、`future_tolerance_hours` |
| 测试 | `tests/test_fetch.py` | 503/超时重试、404 不重试、未来时间 clamp、feed 入口、健康提示 |
| 测试 | `tests/test_score.py` | future_timestamp recency 惩罚 |
| 测试 | `tests/test_summarize.py` | cache key 含 provider/model；无效/部分 JSON 写入 errors |
| 测试 | `tests/test_cli.py`、`tests/test_util.py` 等 | 前几轮回归保持通过 |

## 设计要点 / 关键决策

1. **只重试可恢复错误**：超时、429、5xx 重试；403/404 不重试，避免无意义等待。
2. **未来时间 clamp + 惩罚**：clamp 防止继续产生未来条目；recency × 0.3 防止异常时间占据榜首；原始时间写入 `original_published_at` 便于排查。
3. **InfoQ 的固定偏移优先**：时区问题仍应优先用 `timezone_offset_hours` 修正，通用 guard 只是兜底。
4. **cache key 变更是一次性成本**：部署后首次运行会 miss 旧 cache，最多重新分析 `max_items` 条；之后恢复缓存命中。
5. **前端只允许 http/https**：外链统一走 `safeUrl()`；非法 tab 回退 all，避免空高亮。

## 验证

| 验证项 | 结果 |
|---|---|
| 单元测试 | `python -m pytest -q` → **48 passed** |
| 重试 | 503 → 200 重试成功；404 只请求一次；Timeout → 200 重试成功 |
| 未来时间 | 明天的时间戳被 clamp，original_published_at 保留；健康页出现 future-dated 提示 |
| 评分 | future_timestamp 条目分数低于同条件正常条目 |
| LLM cache | 不同 model/provider 生成不同 cache key |
| LLM 解析 | 非 JSON / 1/2 行返回都会写入 `stats["errors"]`，同时 fallback |
| 前端 | `node --check web/app.js` 通过；`?tab=bogus` 回退 all；非 http(s) URL 渲染为 `#` |
| 线上 | 待后续 Actions 运行验证；本地不重跑全量采集 |

复现命令：

```bash
cd D:\projects\tech-radar
python -m pytest -q
python -m radar run --only inside_java,spring_blog --no-llm --out <tmp>/data --public <tmp>/public
```

## 复发处理

1. **源仍然频繁 error**：看 `health.error` 是否为 4xx（不重试）或重试耗尽；检查 `retry_attempts`、`retry_backoff_seconds` 和 `Retry-After`。
2. **卡片出现“时间异常”**：核对源 `timezone_offset_hours`；如果是固定偏差，优先改配置而不是依赖 clamp。
3. **LLM 费用突然升高**：确认是否刚切换 model/provider（cache key 变更导致一次性 miss）；看 `stats.llm.calls/errors`。
4. **前端链接打不开**：检查 `safeUrl()` 是否把非 http(s) 链接置为 `#`；深链 tab 必须在 `ALLOWED_TABS` 内。

## 相关资料

- 线上数据：<https://xzk-abao.github.io/tech-radar/data/items.json>
- 采集实现：`../../../radar/fetch.py`
- 评分：`../../../radar/score.py`
- LLM：`../../../radar/summarize.py`
- 前端：`../../../web/app.js`
- 测试：`../../../tests/test_fetch.py`、`../../../tests/test_score.py`、`../../../tests/test_summarize.py`
- 上一版归档：`../2026-11-02-数据质量修复/`
