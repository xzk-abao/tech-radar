# 2026-10-31 技术雷达 v1

- **状态**：已完成（本地可运行，待部署 GitHub Pages）
- **需求来源**：用户提出“做一个雷达工具，实时搜索 GitHub 和知名网站的热门工具/知识点，总结分析，先看有没有类似工具”
- **涉及端**：Python 采集管线 + 静态网页仪表盘 + GitHub Actions 定时任务
- **完成时间**：2026-10-31
- **项目路径**：`D:\projects\tech-radar`

## 背景与目标

用户需要一个能“看”的技术情报面板，优先级明确：

1. 官方文档 / Release Notes
2. GitHub 热门项目与趋势
3. 知名高质量学习网站
4. 自动总结、分析和沉淀知识点
5. 周期更新，有可视化界面

验收标准：

- 三类源均可配置、可启停、可查看健康状态
- 采集 → 去重 → 评分 → 总结 → 静态页全链路可本地跑通
- 无 LLM key 时自动降级，不阻塞主流程
- 有 key 时为高价值条目生成摘要、推荐理由和知识卡片
- 单元测试覆盖 URL 归一化、去重、评分、落盘与构建

## 调研结论（PFE + 外部）

内部已有能力：

- `ai-news-briefing`：已包含每日 7 轮搜索、AI 工具雷达、22:00 学习点提取、ECS cron 链路
- `blogwatcher`：RSS/Atom 监控 CLI
- 结论：分析能力已有约 70%，缺口是“结构化采集 + 历史沉淀 + 界面”

外部候选：

| 候选 | 结论 |
|---|---|
| LearnPrompt/ai-news-radar（MIT，约 1.8k★） | 最接近；UI/管线成熟，但强依赖 AI 新闻过滤，源结构与“官方优先”不匹配，最终只借鉴设计 |
| sansan0/TrendRadar（GPL-3.0，约 63k★） | 中文热点/舆情强，GPL 传染，不做产品依赖 |
| newsnext/newsnow、DailyHotApi | 热点聚合，无知识提炼 |
| AES/ThoughtWorks tech radar | 人工策展，不是实时采集 |
| RSSHub / changedetection / Miniflux / Huginn | 可用数据源/监控层，不直接提供雷达产品 |

最终决策：**借鉴自研**。自建轻量 Python 管线 + 静态仪表盘；复用公开 RSS/API；不 fork 297KB 的 AI 新闻单体脚本，不复制 GPL/AGPL 代码。

## 改动内容

| 模块 | 文件 | 内容 |
|---|---|---|
| 源配置 | `config/sources.json` | 19 个 v1 源；tier/weight/type/enabled；评分、多样性、LLM 配置 |
| 抓取 | `radar/fetch.py` | RSS/Atom、GitHub Search、GitHub Trending、Watchlist Releases、页面指纹监控；并发抓取；单源失败隔离 |
| 归一化 | `radar/util.py` | URL 去 tracking、时间解析、HTML 清洗、稳定 ID、标题 token |
| 去重 | `radar/dedupe.py` | URL/标题相似度/版本号保护/同仓库合并；多源成员保留 |
| 评分 | `radar/score.py` | 来源权重 + 时效半衰期 + GitHub 动量 + 学习价值；同源多样性衰减；star 历史 |
| 总结 | `radar/summarize.py` | DeepSeek / 火山方舟；批量 JSON；缓存；无 key 自动 fallback |
| 存储/构建 | `radar/store.py` | `data/items.json`、每日 history 快照、静态站复制 |
| CLI | `radar/cli.py` | `run / build / serve / check / demo` |
| 前端 | `web/index.html`、`web/styles.css`、`web/app.js` | 官方/GitHub/学习/知识卡片/源健康；搜索、时间筛选、排序、动量榜、14 天产出 |
| 自动化 | `.github/workflows/radar.yml` | 每 2 小时采集；测试；Pages 部署；`actions/cache` 持久化 state/history |
| 测试 | `tests/` | 17 个用例，覆盖 util/dedupe/score/store/fetch 过滤 |

## 设计要点 / 关键决策

1. **三层源优先级**：官方 57 条、GitHub 39 条、学习 56 条（本次运行），UI 用 tab 分离，避免信息混在一起。
2. **页面指纹监控**：Anthropic News、DeepSeek News、火山方舟 Docs 没有稳定 feed，首次运行只记录 hash（`baseline`），变化后才产出条目。
3. **GitHub 新仓降噪**：Search API 加 `fork:false archived:false stars:>100`，再用 AI 关键词和垃圾词过滤；Trending 额外屏蔽 jailbreak/算命等无关内容。
4. **评分 + 多样性**：单源前 2 条不衰减，之后按 0.94 递减，避免一个高产博客刷屏。
5. **LLM 可选**：无 `DEEPSEEK_API_KEY` / `ARK_API_KEY` 时，使用规则摘要和 tier 级推荐理由；知识卡片为空，但页面、筛选、源健康全部可用。
6. **成本控制**：只分析 score ≥ 35 的前 30 条；按内容 hash 缓存；批量 8 条/请求。
7. **无状态 runner 持久化**：GitHub Actions 每次运行都是新环境，用 `actions/cache` 恢复 `data/state` 和 `data/history`，否则监控指纹和 star 历史会丢。
8. **许可证边界**：只消费公开 RSS/API；不复制 GPL/AGPL 项目代码；LLM 输出只做摘要，不转载全文。

## 验证

| 验证项 | 结果 |
|---|---|
| 单元测试 | `python -m pytest -q` → **23 passed** |
| 真实采集（本机，19 源，多次运行） | **130–152 条**；14–18/19 源健康；波动来自本机访问 github.com / anthropic.com 的网络 |
| DeepSeek 接入 | **24 张知识卡片，1 次新调用 + 29 次缓存命中，0 报错**；未命中条目自动降级 |
| Obsidian 导出 | `AI\04-资料库\AI工具雷达\2026-10-31-技术雷达.md`（23KB）；标记块外的手写内容不会被覆盖 |
| 演示模式 | `python -m radar demo` → 11 条、4 张知识卡片，UI 正常 |
| 页面功能 | 浏览器实测：6 个 tab、搜索、24h/7d/30d 筛选、按时间排序、源健康表 |
| 控制台 | 无 JS 错误（仅 favicon 404，已用内联 SVG 修复） |
| 关键截图 | `evidence/dashboard-desktop.png`、`evidence/dashboard-knowledge.png` |

> 接入 LLM 时发现一个稳定性问题：某个源临时超时会导致其上一轮条目从页面消失。已增加 `carry_forward_failed_sources`：失败源的旧条目会续用并标「缓存」，健康页仍显示 error，避免一次网络抖动丢掉整块数据。

复现命令：

```bash
cd D:\projects\tech-radar
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python -m radar run --no-llm
python -m radar serve --port 8787
```

## 已知限制

- 本机网络访问 `www.anthropic.com`、部分 `github.com` 原始页面会超时；正式采集跑 GitHub Actions。
- GitHub Trending 无官方 API，页面解析可能随改版失效；源健康页会暴露错误。
- OpenAI changelog 对脚本 403，使用 OpenAI News RSS 替代。
- 未配置 LLM key 时知识卡片为空，这是预期降级。
- 只保存标题、摘要、链接，不保存全文。

## 后续（Roadmap）

1. 部署到 GitHub Pages，配置 `DEEPSEEK_API_KEY` secret，观察一周源健康。
2. ✅ 知识卡片导出到 `D:\mdStudy\personal-knowledge-base\AI\04-资料库\AI工具雷达\`（已实现 `python -m radar export`，用标记块保护手写内容）。
3. Phase 2：Java 21 + Spring Boot + LangChain4j 重写采集/分析，复用同一静态前端（可作为作品集）。
4. 历史趋势页、主题雷达图、企业微信/飞书推送。

## 相关资料

- 项目 README：`../../../README.md`
- 桌面截图：`evidence/dashboard-desktop.png`
- 知识卡片截图：`evidence/dashboard-knowledge.png`
- 源清单：`../../../config/sources.json`
