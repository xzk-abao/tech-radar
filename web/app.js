(() => {
  "use strict";

  const state = {
    dataset: null,
    history: [],
    tab: "all",
    search: "",
    time: 168,
    sort: "score",
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const TIER_LABEL = { official: "官方动态", github: "GitHub 趋势", learning: "学习精选" };
  const TIER_CLASS = { official: "official", github: "github", learning: "learning" };

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function parseDate(value) {
    const date = new Date(value || "");
    return Number.isNaN(date.getTime()) ? new Date() : date;
  }

  function ageHours(value) {
    return Math.max(0, (Date.now() - parseDate(value).getTime()) / 36e5);
  }

  function timeAgo(value) {
    const minutes = Math.round(ageHours(value) * 60);
    if (minutes < 1) return "刚刚";
    if (minutes < 60) return `${minutes} 分钟前`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours} 小时前`;
    const days = Math.round(hours / 24);
    if (days < 30) return `${days} 天前`;
    const months = Math.round(days / 30);
    return `${months} 个月前`;
  }

  function fmtDateTime(value) {
    const date = parseDate(value);
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
    }).format(date);
  }

  function dayKey(value) {
    const date = parseDate(value);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  function dayLabel(value) {
    const target = dayKey(value);
    const today = dayKey(new Date());
    const yesterday = dayKey(new Date(Date.now() - 864e5));
    if (target === today) return "今天";
    if (target === yesterday) return "昨天";
    const date = parseDate(value);
    return `${date.getMonth() + 1} 月 ${date.getDate()} 日`;
  }

  function fmtNumber(value) {
    const num = Number(value || 0);
    if (num >= 10000) return `${(num / 10000).toFixed(1)}w`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}k`;
    return String(num);
  }

  function matchesSearch(item, query) {
    if (!query) return true;
    const haystack = [
      item.title, item.summary, item.why, item.source_name,
      ...(item.tags || []),
      item.knowledge ? `${item.knowledge.concept} ${item.knowledge.one_liner} ${item.knowledge.why_it_matters}` : "",
    ].join(" ").toLowerCase();
    return query.split(/\s+/).every((term) => haystack.includes(term));
  }

  function visibleItems() {
    if (!state.dataset) return [];
    let items = (state.dataset.items || []).slice();

    if (state.tab === "official" || state.tab === "github" || state.tab === "learning") {
      items = items.filter((item) => item.tier === state.tab);
    }
    if (state.tab === "knowledge") {
      items = items.filter((item) => item.knowledge);
    }
    if (state.time > 0) {
      items = items.filter((item) => ageHours(item.published_at) <= state.time);
    }
    if (state.search) {
      items = items.filter((item) => matchesSearch(item, state.search));
    }
    if (state.sort === "latest") {
      items.sort((a, b) => parseDate(b.published_at) - parseDate(a.published_at));
    } else {
      items.sort((a, b) => (b.score || 0) - (a.score || 0));
    }
    return items;
  }

  function renderStats() {
    const stats = (state.dataset && state.dataset.stats) || {};
    const tiers = stats.by_tier || {};
    const coverage = Number.isFinite(stats.sources_with_items)
      ? `${stats.sources_with_items}/${stats.sources_total || 0} 源有产出 · `
      : "";
    const cards = [
      ["本期条目", stats.total_items || 0, `${coverage}${stats.clusters || 0} 个事件簇`],
      ["官方动态", tiers.official || 0, "发布 · 文档 · 版本"],
      ["GitHub 趋势", tiers.github || 0, "新仓 · 升温 · 发版"],
      ["学习精选", tiers.learning || 0, "教程 · 实战 · 架构"],
      ["知识卡片", stats.knowledge_cards || 0, "可沉淀的知识点"],
    ];
    $("#stats").innerHTML = cards.map(([label, value, sub]) => `
      <div class="stat">
        <div class="stat-label">${esc(label)}</div>
        <div class="stat-value">${esc(value)}</div>
        <div class="stat-sub">${esc(sub)}</div>
      </div>
    `).join("");
  }

  function renderHero() {
    if (!state.dataset) return;
    const stats = state.dataset.stats || {};
    const generated = state.dataset.generated_at;
    $("#updated").textContent = generated ? fmtDateTime(generated) : "--";
    $("#totalItems").textContent = String(stats.total_items || 0);
    const ok = stats.sources_ok || 0;
    const total = stats.sources_total || 0;
    const stale = stats.sources_stale || 0;
    const withItems = stats.sources_with_items;
    const ratio = total ? ok / total : 0;
    const pill = $("#healthPill");
    const hints = [];
    if (Number.isFinite(withItems)) hints.push(`${withItems} 个源有最终条目`);
    if (stale) hints.push(`${stale} 个源最近条目已超出保留窗口`);
    pill.textContent = `${ok}/${total}`;
    pill.title = hints.join("；");
    pill.className = `pill${ratio < 0.5 ? " bad" : ratio < 0.8 || stale > 0 ? " warn" : ""}`;
    $("#demoBanner").classList.toggle("hidden", !state.dataset.demo);
    $("#footerStats").textContent = `${total} 个源 · LLM ${stats.llm && stats.llm.model ? stats.llm.model : "fallback"}`;
  }

  function knowledgeBlock(knowledge) {
    if (!knowledge || !knowledge.concept) return "";
    const path = Array.isArray(knowledge.learning_path) ? knowledge.learning_path : [];
    const difficulty = Number(knowledge.difficulty);
    return `
      <div class="knowledge">
        <div class="knowledge-head">
          <span>知识卡片</span>
          ${Number.isFinite(difficulty) ? `<span class="difficulty">难度 ${esc(difficulty)}/5</span>` : ""}
        </div>
        <h4>${esc(knowledge.concept)}</h4>
        ${knowledge.one_liner ? `<p>${esc(knowledge.one_liner)}</p>` : ""}
        ${knowledge.why_it_matters ? `<p>${esc(knowledge.why_it_matters)}</p>` : ""}
        ${path.length ? `<div class="path">${path.map((step) => `<span>${esc(step)}</span>`).join("")}</div>` : ""}
      </div>
    `;
  }

  function membersBlock(item) {
    if (!item.members || item.members.length < 2) return "";
    const sourceCount = new Set(item.members.map((member) => member.source_name)).size;
    const label = sourceCount > 1 ? `多源 ${item.members.length}` : `同事件 ${item.members.length}`;
    return `
      <details class="members">
        <summary>${esc(label)}</summary>
        <ul class="member-list">
          ${item.members.map((member) => `
            <li>${esc(member.source_name)} · <a href="${esc(member.url)}" target="_blank" rel="noopener noreferrer">${esc(member.title)}</a></li>
          `).join("")}
        </ul>
      </details>
    `;
  }

  function card(item) {
    const tier = TIER_CLASS[item.tier] || "learning";
    const score = Math.max(0, Math.min(100, Number(item.score || 0)));
    return `
      <article class="card">
        <div class="card-top">
          <span class="badge ${tier}">${esc(TIER_LABEL[item.tier] || item.tier)}</span>
          ${item.extra && item.extra.carried_forward ? '<span class="badge cached">缓存</span>' : ""}
          <span class="source">${esc(item.source_name)}</span>
          <span class="dot"></span>
          <span class="time" title="${esc(item.published_at)}">${esc(timeAgo(item.published_at))}</span>
          <span class="score">
            <span class="score-num">${esc(Math.round(score))}</span>
            <span class="score-bar"><i style="width:${score}%"></i></span>
          </span>
        </div>
        <h3><a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></h3>
        ${item.summary ? `<p class="summary">${esc(item.summary)}</p>` : ""}
        ${item.why ? `<p class="why">为什么值得看：${esc(item.why)}</p>` : ""}
        ${(item.tags || []).length ? `<div class="tags">${item.tags.slice(0, 8).map((tag) => `<span class="tag">${esc(tag)}</span>`).join("")}</div>` : ""}
        ${knowledgeBlock(item.knowledge)}
        ${membersBlock(item)}
      </article>
    `;
  }

  function renderFeed() {
    const feed = $("#feed");
    const items = visibleItems();
    if (!items.length) {
      if (state.tab === "knowledge") {
        feed.innerHTML = `<div class="empty"><strong>还没有知识卡片</strong>配置 <code>DEEPSEEK_API_KEY</code> 或火山方舟后重新运行，LLM 会为高价值条目生成知识点。<br>也可以先运行 <code>python -m radar demo</code> 预览卡片样式。</div>`;
        return;
      }
      feed.innerHTML = `<div class="empty"><strong>没有匹配的条目</strong>试试放宽时间范围、清空搜索，或先运行一次采集。</div>`;
      return;
    }

    const parts = [];
    let lastDay = "";
    for (const item of items) {
      if (state.sort === "latest") {
        const key = dayKey(item.published_at);
        if (key !== lastDay) {
          parts.push(`<div class="day-label">${esc(dayLabel(item.published_at))}</div>`);
          lastDay = key;
        }
      }
      parts.push(card(item));
    }
    feed.innerHTML = parts.join("");
  }

  function renderMomentum() {
    const items = ((state.dataset && state.dataset.items) || [])
      .filter((item) => item.tier === "github" && (item.extra && (item.extra.stars || item.extra.stars_today || item.extra.star_delta_7d)))
      .sort((a, b) => {
        const score = (item) => Number((item.extra && (item.extra.star_delta_7d || item.extra.stars_today)) || 0);
        return score(b) - score(a) || (b.score || 0) - (a.score || 0);
      })
      .slice(0, 5);

    const root = $("#momentum");
    if (!items.length) {
      root.innerHTML = `<div class="mini-meta">本次没有抓到 GitHub 动量数据</div>`;
      return;
    }
    root.innerHTML = items.map((item, index) => {
      const extra = item.extra || {};
      const delta = extra.star_delta_7d ? `+${fmtNumber(extra.star_delta_7d)}/7d` : extra.stars_today ? `今日 +${fmtNumber(extra.stars_today)}` : "";
      const stars = extra.stars ? `★ ${fmtNumber(extra.stars)}` : "";
      return `
        <div class="mini">
          <span class="mini-rank">${String(index + 1).padStart(2, "0")}</span>
          <div class="mini-body">
            <a class="mini-title" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a>
            <div class="mini-meta">${esc(stars)}${stars && delta ? " · " : ""}<b>${esc(delta)}</b></div>
          </div>
        </div>
      `;
    }).join("");
  }

  function renderKnowledgeMini() {
    const items = ((state.dataset && state.dataset.items) || [])
      .filter((item) => item.knowledge && item.knowledge.concept)
      .slice(0, 4);
    const root = $("#knowledgeMini");
    if (!items.length) {
      root.innerHTML = `<div class="mini-meta">配置 LLM 后会自动生成知识卡片</div>`;
      return;
    }
    root.innerHTML = items.map((item) => `
      <div class="mini">
        <div class="mini-body">
          <a class="mini-title" href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.knowledge.concept)}</a>
          <div class="mini-meta">${esc(item.knowledge.one_liner || "")}</div>
        </div>
      </div>
    `).join("");
  }

  function renderHistory() {
    const root = $("#historyChart");
    const rows = state.history.slice(-14);
    if (!rows.length) {
      root.innerHTML = `<div class="mini-meta">历史数据会在每天运行后累积</div>`;
      return;
    }
    const max = Math.max(...rows.map((row) => Number(row.total_items || 0)), 1);
    root.innerHTML = rows.map((row) => {
      const height = Math.max(6, Math.round((Number(row.total_items || 0) / max) * 100));
      const label = String(row.date || "").slice(5);
      return `<div class="hbar" title="${esc(row.date)} · ${esc(row.total_items)} 条"><i style="height:${height}%"></i><span>${esc(label)}</span></div>`;
    }).join("");
  }

  function renderHealth() {
    const rows = ((state.dataset && state.dataset.health) || []).slice().sort((a, b) => {
      const order = { official: 0, github: 1, learning: 2 };
      return (order[a.tier] ?? 9) - (order[b.tier] ?? 9) || String(a.source_id).localeCompare(String(b.source_id));
    });
    const tbody = $("#healthTable tbody");
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="6">暂无源健康数据</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((row) => {
      const effective = row.effective_items == null ? row.items : row.effective_items;
      const count = effective === row.items
        ? esc(row.items || 0)
        : `${esc(row.items || 0)}<br><span class="mini-meta">有效 ${esc(effective)}</span>`;
      return `
        <tr>
          <td>${esc(row.source_name)}<br><span class="mini-meta">${esc(row.source_id)}</span></td>
          <td>${esc(TIER_LABEL[row.tier] || row.tier)}</td>
          <td><span class="status ${esc(row.status)}">${esc(row.status)}</span></td>
          <td>${count}</td>
          <td>${row.last_item_at ? esc(fmtDateTime(row.last_item_at)) : "--"}</td>
          <td class="err-text ${esc(row.status)}">${esc(row.error || "")}</td>
        </tr>
      `;
    }).join("");
  }

  function render() {
    if (!state.dataset) return;
    renderHero();
    renderStats();
    renderMomentum();
    renderKnowledgeMini();
    renderHistory();
    renderHealth();

    const isHealth = state.tab === "health";
    $("#mainLayout").classList.toggle("hidden", isHealth);
    $("#healthView").classList.toggle("hidden", !isHealth);
    if (!isHealth) renderFeed();

    $$("#tabs button").forEach((button) => {
      button.classList.toggle("active", button.dataset.tab === state.tab);
    });
  }

  function setTab(tab, updateHash = true) {
    const allowed = ["all", "official", "github", "learning", "knowledge", "health"];
    state.tab = allowed.includes(tab) ? tab : "all";
    if (updateHash) {
      history.replaceState(null, "", state.tab === "all" ? location.pathname : `#${state.tab}`);
    }
    render();
  }

  function bindEvents() {
    $$("#tabs button").forEach((button) => {
      button.addEventListener("click", () => {
        setTab(button.dataset.tab);
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    });

    let timer = null;
    $("#search").addEventListener("input", (event) => {
      clearTimeout(timer);
      const value = event.target.value.trim().toLowerCase();
      timer = setTimeout(() => {
        state.search = value;
        render();
      }, 140);
    });

    $("#timeFilter").addEventListener("change", (event) => {
      state.time = Number(event.target.value);
      render();
    });

    $("#sort").addEventListener("change", (event) => {
      state.sort = event.target.value;
      render();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "/" && document.activeElement !== $("#search")) {
        event.preventDefault();
        $("#search").focus();
      }
      if (event.key === "Escape" && document.activeElement === $("#search")) {
        $("#search").value = "";
        state.search = "";
        $("#search").blur();
        render();
      }
    });
  }

  async function loadHistory() {
    try {
      const response = await fetch("data/history/index.json", { cache: "no-store" });
      if (response.ok) state.history = await response.json();
    } catch (error) {
      state.history = [];
    }
  }

  async function init() {
    bindEvents();
    const params = new URLSearchParams(location.search);
    const initialTab = params.get("tab") || location.hash.replace("#", "");
    if (initialTab) state.tab = initialTab;
    window.addEventListener("hashchange", () => {
      setTab(location.hash.replace("#", ""), false);
    });
    try {
      const response = await fetch("data/items.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.dataset = await response.json();
      await loadHistory();
      render();
    } catch (error) {
      $("#feed").innerHTML = `<div class="empty"><strong>数据还没有生成</strong>先运行 <code>python -m radar run</code>，或查看 README 的本地运行说明。<br><span class="mini-meta">${esc(error.message)}</span></div>`;
    }
  }

  init();
})();
