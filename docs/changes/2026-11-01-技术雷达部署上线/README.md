# 2026-11-01 技术雷达 GitHub Pages 上线

- **状态**：已上线
- **需求来源**：技术雷达 v1 收尾（P0：接入 GitHub Actions 定时采集并部署 Pages，验证生产网络下的源健康）
- **涉及端**：GitHub Actions 采集管线 + GitHub Pages 静态站
- **完成时间**：2026-11-01

## 背景与目标

v1 已在本机跑通，但数据停在 2026-10-31 15:56，且项目没有远程仓库、没有定时任务。本次目标：

- 代码进入版本控制并推送到 GitHub
- 每 2 小时由 Actions 自动采集、构建、部署
- 提供公开可访问的 Pages 地址
- LLM key 只通过 Actions Secret 注入，不进入仓库
- 用生产 runner 验证本机受网络限制的源是否可达

验收标准：首轮 workflow 成功；线上 `data/items.json` 非 demo；19 个源全部完成检查；页面可访问且无 JS 错误。

## 改动内容

| 项 | 内容 |
|---|---|
| 本地版本控制 | `git init -b main`；首次提交 `f22c796 feat: initial tech radar v1`（36 个文件） |
| 远程仓库 | 创建 public 仓库 `xzk-abao/tech-radar` |
| 推送 | SSH remote `git@github.com:xzk-abao/tech-radar.git`；本机 `GITHUB_TOKEN` 只有 `repo` scope，HTTPS 推送含 workflow 文件会被 `workflow` scope 拦截，改用 SSH |
| Pages | `POST /repos/xzk-abao/tech-radar/pages`，`build_type=workflow`，由 GitHub Actions 发布 |
| Secret | `DEEPSEEK_API_KEY` 通过仓库 Actions 公钥加密写入 secret；值未落盘、未进入提交 |
| 自动化 | `.github/workflows/radar.yml`：push / 手动触发 + 每 2 小时 schedule；`actions/cache` 持久化 `data/state` 与 `data/history` |
| 前端深链 | `web/app.js`：支持 `?tab=knowledge`、`#knowledge`、`#health`，第二次部署后上线 |

## 设计要点 / 关键决策

1. **仓库选 public**：GitHub Pages 对公开仓库免费；私有仓库的 Pages 需要付费计划。
2. **`data/` 和 `public/` 继续保持 gitignore**：runner 无状态，线上数据由 Actions 每次重建；monitor 指纹、star 历史、LLM 缓存通过 cache 恢复。
3. **SSH 推送**：classic PAT 缺少 `workflow` scope 时无法通过 HTTPS 更新 `.github/workflows/*`；SSH key 已在本机配置并验证为 `xzk-abao`。
4. **首轮 baseline 属于预期**：3 个 `html_monitor` 源在首轮只记录页面指纹，不产出条目；下一轮检测到变化才产出。
5. **LLM 可选但本次已启用**：secret 注入成功，首轮 4 次新调用、0 错误；未命中 LLM 的条目自动降级为规则摘要。

## 验证

| 验证项 | 结果 |
|---|---|
| CI 单元测试 | **23 passed**（workflow 的 Run tests 步骤成功） |
| Workflow run（首轮） | [41301830363](https://github.com/xzk-abao/tech-radar/actions/runs/41301830363)：build success（11:25:42–11:26:43 UTC），deploy success（11:26:47–11:27:01 UTC） |
| Workflow run（深链） | [41308522290](https://github.com/xzk-abao/tech-radar/actions/runs/41308522290)：build success（12:52:16–12:52:35 UTC），deploy success（12:52:39–12:52:50 UTC）；线上 155 条 / 24 张卡片；`?tab=knowledge`、`#health` 深链实测通过，控制台 0 error；截图 `evidence/live-knowledge.png` |
| 线上页面 | <https://xzk-abao.github.io/tech-radar/> → HTTP 200，标题「技术雷达 · Tech Radar」 |
| 线上数据 | `data/items.json` → **155 条**；official 57 / github 42 / learning 56；**24 张知识卡片**；`generated_at=2026-11-01T11:26:37Z`；`demo=false` |
| 源健康 | **19/19 ok，0 error**；3 个 baseline（anthropic_news、deepseek_docs、volcengine_ark_docs）；14 个源有最终条目 |
| LLM | provider=deepseek，model=deepseek-chat，calls=4，hits=0，fallbacks=125，errors=[] |
| 浏览器 | Playwright 实测：控制台 **0 error / 0 warning**；截图见 `evidence/live-home.png` |
| Secret 安全 | 仓库内无明文 key；扫描 `sk-*`、PAT、私钥特征均无命中 |

## 附带发现

- **JavaGuide 源实际失效**：feed 最新条目停在 2026-08-16，健康状态 ok 但被 30 天窗口过滤后最终 0 条；已禁用并替换为 Inside Java（见 `../2026-11-01-数据源质量修复/`）。
- **InfoQ 时间戳偏差**：feed 把北京时间标成 GMT；线上快照有 5 条未来时间条目（最多 +7.8h），`recency` 会被钳到满分，排名偏高。已通过 `timezone_offset_hours: -8` 修正（见 `../2026-11-01-数据源质量修复/`）。
- 首轮 `anthropic_news` 只建立 baseline：此前本机访问超时，未留下指纹；下一轮才会产出变更条目。

## 复发处理

1. **页面不更新**：先看 Actions run 是否被 schedule 触发；检查 workflow 是否 active、Pages source 是否仍为 GitHub Actions、`DEEPSEEK_API_KEY` secret 是否存在。
2. **源健康异常**：区分 runner 网络问题与源本身失效；健康页 error 不等于数据全丢，失败源有 carry-forward 缓存。
3. **历史 / 动量丢失**：检查 `actions/cache` 是否命中；cache 7 天不访问会被清理，但 2 小时 schedule 正常不会触发。
4. **需要手动补跑**：Actions → tech-radar → Run workflow，或 `workflow_dispatch`。

## 相关资料

- 线上地址：<https://xzk-abao.github.io/tech-radar/>
- 仓库：<https://github.com/xzk-abao/tech-radar>
- 首轮 run：<https://github.com/xzk-abao/tech-radar/actions/runs/41301830363>
- 深链部署 run：<https://github.com/xzk-abao/tech-radar/actions/runs/41308522290>
- workflow：`../../../.github/workflows/radar.yml`
- 截图：`evidence/live-home.png`、`evidence/live-knowledge.png`
- 上一版归档：`../2026-10-31-技术雷达v1/`
