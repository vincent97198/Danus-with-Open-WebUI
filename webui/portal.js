(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const state = { projects: [], trash: [], loaded: false, name: '', tab: 'progress', mode: 'projects', info: null, progress: null, results: null, busy: false, serial: 0 };
  const rendered = new Map();
  const escape = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const storage = {
    get(key) { try { return localStorage.getItem('danus.' + key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem('danus.' + key, value); } catch { /* private browsing */ } }
  };
  const apiPath = (name = state.name) => '/api/danus/projects/' + encodeURIComponent(name);
  const selected = () => state.projects.find((p) => p.project === state.name);
  const isRunning = () => state.progress?.workers?.some((w) => w.alive) ?? Boolean(selected()?.live);
  const date = (value) => {
    if (!value) return '尚無記錄';
    const d = new Date(typeof value === 'number' ? value * 1000 : value);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-TW', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };
  const duration = (seconds) => {
    if (!Number.isFinite(seconds)) return '—';
    const minutes = Math.floor(seconds / 60);
    return minutes >= 60 ? Math.floor(minutes / 60) + ' 小時 ' + minutes % 60 + ' 分' : minutes > 0 ? minutes + ' 分 ' + Math.floor(seconds % 60) + ' 秒' : Math.floor(seconds) + ' 秒';
  };
  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 60000);
    try {
      const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers }, signal: controller.signal });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : '暫時無法完成操作，請稍後重試。');
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('連線逾時，請重新整理確認狀態。');
      if (error instanceof TypeError) throw new Error('連不上工作區，請確認 Docker Desktop 正在執行。');
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function setHTML(id, html, math = false) {
    if (rendered.get(id) === html) return;
    $(id).innerHTML = html;
    rendered.set(id, html);
    if (math && window.renderMathInElement) {
      window.renderMathInElement($(id), { throwOnError: false, trust: false, delimiters: [
        { left: '$$', right: '$$', display: true }, { left: '\\[', right: '\\]', display: true },
        { left: '\\(', right: '\\)', display: false }, { left: '$', right: '$', display: false }
      ] });
    }
  }
  // Keep model output inert before rendering formulas. Only ordinary document markup is allowed.
  function markdown(value) {
    const text = typeof value === 'string' ? value : JSON.stringify(value ?? '', null, 2);
    if (!window.marked) return '<p>' + escape(text).replace(/\n/g, '<br>') + '</p>';
    const math = [];
    const protectedText = text.replace(/\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(?<!\\)\$[^\n$]+?\$/g, (m) => {
      math.push(m);
      return 'DANUSMATHPLACEHOLDER' + (math.length - 1) + 'END';
    });
    const doc = new DOMParser().parseFromString(marked.parse(protectedText, { gfm: true, breaks: false }), 'text/html');
    const allow = new Set(['P','BR','HR','H1','H2','H3','H4','H5','H6','UL','OL','LI','STRONG','EM','DEL','BLOCKQUOTE','PRE','CODE','TABLE','THEAD','TBODY','TR','TH','TD','A','SUP','SUB']);
    for (const node of [...doc.body.querySelectorAll('*')]) {
      if (!allow.has(node.tagName)) { node.replaceWith(doc.createTextNode(node.textContent)); continue; }
      const href = node.getAttribute('href');
      for (const attr of [...node.attributes]) node.removeAttribute(attr.name);
      if (node.tagName === 'A' && href && /^https?:\/\//i.test(href)) {
        node.setAttribute('href', href); node.setAttribute('target', '_blank'); node.setAttribute('rel', 'noopener noreferrer');
      }
    }
    return doc.body.innerHTML.replace(/DANUSMATHPLACEHOLDER(\d+)END/g, (_, i) => escape(math[Number(i)] ?? ''));
  }
  function projectStatus(project, workers = project?.workers_detail || []) {
    if (workers.some((w) => w.alive && w.stop_requested)) return { label: '等待本輪結束', color: 'amber' };
    if (workers.some((w) => w.alive) || project?.live) return { label: '推理中', color: 'green' };
    if (workers.some((w) => w.state === 'error')) return { label: '執行遇到問題', color: 'red' };
    if (workers.some((w) => w.round > 0)) return { label: '已停止', color: '' };
    return { label: '尚未開始', color: '' };
  }
  function renderProjects() {
    const query = $('project-search').value.trim().toLowerCase();
    const rows = state.projects.filter((p) => (p.title + ' ' + p.project).toLowerCase().includes(query));
    $('project-count').textContent = state.projects.length;
    setHTML('project-list', rows.length ? rows.map((p) => {
      const status = projectStatus(p);
      return '<button class="project-item ' + (p.project === state.name && state.mode === 'projects' ? 'selected' : '') + '" data-project="' + escape(p.project) + '" aria-current="' + (p.project === state.name && state.mode === 'projects' ? 'page' : 'false') + '" title="' + escape(p.title) + '"><strong>' + escape(p.title) + '</strong><small><span class="status-dot ' + status.color + '"></span>' + status.label + '<em>' + (p.fact_count || 0) + ' 項成果</em></small></button>';
    }).join('') : '<p class="sidebar-empty">' + (query ? '找不到符合的專案' : '還沒有專案，按上方 ＋ 開始。') + '</p>');
  }
  function route(mode, name = state.name, tab = state.tab) {
    const query = new URLSearchParams();
    if (mode === 'projects' && name) { query.set('project', name); query.set('tab', tab); }
    const next = '#' + mode + (query.size ? '?' + query.toString() : '');
    if (location.hash === next) readRoute(); else location.hash = next;
  }
  function readRoute() {
    const [rawMode, query = ''] = location.hash.slice(1).split('?');
    const params = new URLSearchParams(query);
    const mode = ['chat', 'trash', 'settings'].includes(rawMode) ? rawMode : 'projects';
    let name = params.get('project') || storage.get('project') || state.projects[0]?.project || '';
    if (state.loaded && !state.projects.some((p) => p.project === name)) name = state.projects[0]?.project || '';
    const project = state.projects.find((p) => p.project === name);
    const defaultTab = ['split', 'results'].includes(rawMode) || project?.fact_count ? 'results' : 'progress';
    const tab = ['progress', 'results', 'literature', 'graph', 'problem'].includes(params.get('tab')) ? params.get('tab') : defaultTab;
    const changed = name !== state.name;
    state.mode = mode; state.name = name; state.tab = tab;
    if (name) storage.set('project', name);
    if (changed) {
      state.serial++; state.info = state.progress = state.results = state.literature = null;
      ['progress-summary', 'activity-list', 'panel-results', 'panel-literature', 'panel-problem'].forEach((id) => setHTML(id, '<div class="inline-empty">正在讀取…</div>'));
      $('graph-frame').src = 'about:blank'; $('graph-frame').hidden = true;
    }
    $('math-view').hidden = mode !== 'projects'; $('chat-view').hidden = mode !== 'chat'; $('trash-view').hidden = mode !== 'trash';
    $('settings-view').hidden = mode !== 'settings';
    $('page-label').textContent = { chat: '聊天', projects: '數學專案', trash: '回收筒', settings: '搜尋設定' }[mode];
    document.querySelectorAll('[data-mode]').forEach((button) => button.classList.toggle('active', button.dataset.mode === mode));
    $('open-trash').classList.toggle('active', mode === 'trash');
    $('open-search-settings').classList.toggle('active', mode === 'settings');
    document.body.classList.remove('mobile-sidebar');
    if (mode === 'chat' && $('chat-frame').src === 'about:blank') $('chat-frame').src = location.protocol + '//' + location.hostname + ':3000/?models=local-research';
    renderProjects(); renderTabs(); renderWorkspace(); renderTrash();
    if (state.loaded && mode === 'projects' && name && (changed || !state.info)) loadCurrent();
  }
  function renderTabs() {
    document.querySelectorAll('[data-tab]').forEach((button) => {
      const active = button.dataset.tab === state.tab;
      button.setAttribute('aria-selected', String(active));
      button.tabIndex = active ? 0 : -1;
      $('panel-' + button.dataset.tab).hidden = !active;
    });
    if (state.tab === 'graph' && state.mode === 'projects') {
      const hasFacts = Boolean(state.results?.fact_count);
      $('graph-frame').hidden = !hasFacts; $('graph-empty').hidden = hasFacts;
      setHTML('graph-empty', '<h2>事實圖還在等待第一個成果</h2><p>通過驗證的命題會顯示為節點，並連結彼此的依賴關係。</p>');
      if (hasFacts) {
        const src = '/dashboard/' + encodeURIComponent(state.name) + '/?embed=graph';
        if ($('graph-frame').getAttribute('src') !== src) $('graph-frame').src = src;
      }
    }
  }
  function renderWorkspace() {
    const p = selected();
    $('empty-state').hidden = Boolean(p); $('project-workspace').hidden = !p;
    if (!p) return;
    $('project-title').textContent = state.info?.title || p.title;
    $('project-id').textContent = p.project;
    $('project-description').textContent = state.info?.problem?.trim() || '正在讀取問題…';
    const search = state.info?.search;
    $('project-search-settings').textContent = search ? '搜尋：' + (search.enabled ? '開啟' : '關閉') : '搜尋設定';
    $('project-search-settings').classList.toggle('search-off', search?.enabled === false);
    const workers = state.progress?.workers || p.workers_detail || [];
    const status = projectStatus(p, workers);
    const running = workers.some((w) => w.alive);
    const round = Math.max(0, ...workers.map((w) => w.round || 0));
    const latestLog = workers.map((w) => w.last_log_at).filter(Boolean).sort().at(-1);
    const facts = state.results?.fact_count ?? p.fact_count ?? 0;
    $('results-count').textContent = facts;
    $('primary-action').textContent = state.busy ? '正在處理…' : running ? '■ 立即停止' : round > 0 ? '▶ 繼續推理' : '▶ 開始推理';
    $('primary-action').className = 'button ' + (running ? 'stop' : 'primary');
    $('primary-action').disabled = state.busy;
    $('graceful-stop').hidden = !running;
    $('graceful-stop').disabled = state.busy || workers.some((w) => w.stop_requested);
    const elapsed = Math.max(0, ...workers.map((w) => w.elapsed_s || 0));
    setHTML('project-stats',
      '<div class="stat"><small>執行狀態</small><strong><span class="status-dot ' + status.color + '"></span>' + status.label + '</strong></div>' +
      '<div class="stat"><small>已驗證成果</small><strong>' + facts + '<span class="unit">項命題</span></strong></div>' +
      '<div class="stat"><small>' + (running ? '目前輪次' : '上次輪次') + '</small><strong>' + (round || '—') + '<span class="unit">' + (running ? '· ' + duration(elapsed) : '輪') + '</span></strong></div>' +
      '<div class="stat"><small>最近工作記錄</small><strong style="font-size:13px">' + date(latestLog) + '</strong></div>');
    renderTabs();
  }
  function renderProgress() {
    if (!state.progress) return;
    const workers = state.progress.workers;
    const running = workers.some((w) => w.alive);
    const stopping = workers.some((w) => w.alive && w.stop_requested);
    const failure = workers.some((w) => !w.alive && w.state === 'error');
    const facts = state.results?.fact_count || 0;
    let message = running ? 'Danus 正在探索與驗證。中間記錄會持續更新；你可以隨時立即停止。'
      : facts ? '專案已停止，已保存 ' + facts + ' 項成果。可以切到「成果」閱讀證明，或繼續推理。'
      : workers.some((w) => w.round > 0) ? '專案已停止，目前尚無通過驗證的成果。可以先檢查工作記錄，再繼續推理。' : '問題已準備好，按右上方「開始推理」即可交給 Danus。';
    if (stopping) message = '已設定本輪結束後停止。這可能需要較久；要現在結束，請按「立即停止」。';
    if (failure) message = '上次執行遇到問題。請查看下方記錄；確認模型連線正常後，可以繼續推理。';
    setHTML('progress-summary', '<div class="notice ' + (failure ? 'error' : running ? '' : 'neutral') + '">' + message + '</div>');
    const events = state.progress.recent_events || [];
    setHTML('activity-list', events.length ? events.slice(0, 10).map((event) => '<article class="activity ' + (event.kind === '錯誤' ? 'error' : '') + '"><span class="activity-icon">' + (event.kind === '錯誤' ? '!' : '↳') + '</span><div class="activity-body"><div class="activity-meta"><span>' + escape(event.kind) + ' · 第 ' + escape(event.round) + ' 輪</span><span>' + (event.time ? date(event.time) : escape(event.worker)) + '</span></div><p>' + escape(event.text) + '</p></div></article>').join('') : '<div class="inline-empty"><h2>' + (running ? '正在準備這一輪' : '尚無工作記錄') + '</h2><p>' + (running ? '模型寫入第一則記錄後，會自動顯示在這裡。' : '開始推理後，這裡會顯示最近活動。') + '</p></div>');
    const logs = workers.map((w) => (workers.length > 1 ? '── ' + w.worker + ' ──\n' : '') + (w.log_tail || '尚無記錄')).join('\n\n');
    if ($('raw-log').textContent !== logs) $('raw-log').textContent = logs;
    $('log-time').textContent = '最後寫入：' + date(workers.map((w) => w.last_log_at).filter(Boolean).sort().at(-1));
  }
  function renderResults() {
    if (!state.results) return;
    const data = state.results;
    let html = '<div class="section-heading"><div><h2>已驗證成果</h2><p>閱讀命題與完整證明，公式會直接顯示。</p></div><button class="button" data-action="download">↓ 下載成果</button></div>';
    if (!data.facts.length) html += '<div class="inline-empty"><h2>尚無通過驗證的成果</h2><p>' + (isRunning() ? 'Danus 還在研究中。可以到「進度」查看目前活動。' : '開始推理後，通過 Danus 驗證的命題會保存在這裡。') + '</p><button class="button" data-action="progress">查看進度</button></div>';
    html += data.facts.map((fact, i) => '<article class="result-card"><div class="result-card-heading"><div class="result-label"><span>✓</span>通過 Danus 驗證 · 成果 ' + (i + 1) + '</div><span class="fact-id">' + escape(fact.fact_id) + '</span></div><div class="prose">' + markdown(fact.statement) + '</div><h3 class="proof-label">證明</h3><div class="prose">' + markdown(fact.proof || '此事實未附獨立證明文字。') + '</div></article>').join('');
    if (data.fact_count > data.facts.length) html += '<p class="result-footnote">目前顯示最近 ' + data.facts.length + ' 項；下載可取得全部成果。</p>';
    if (data.facts.length) html += '<p class="result-footnote">驗證由模型執行。下方可查看驗證記錄，重要結論仍可人工核對。</p>';
    if (data.verifications.length) html += '<details class="verification-list"><summary>查看驗證記錄（' + data.verification_count + '）</summary>' + data.verifications.map((v) => '<article class="verification-item"><p>' + escape(v.verdict) + ' · ' + date(v.timestamp_utc) + (v.fact_id ? ' · ' + escape(v.fact_id) : '') + '</p><div class="prose">' + markdown(v.claim) + '</div><details><summary>驗證說明</summary><div class="prose">' + markdown(v.evidence) + '</div></details></article>').join('') + '</details>';
    setHTML('panel-results', html, true);
  }
  function renderProblem() {
    if (!state.info) return;
    setHTML('panel-problem', '<div class="section-heading"><div><h2>研究問題</h2><p>建立專案時交給 Danus 的目標與條件。</p></div><button class="button" data-action="duplicate">複製並修改</button></div><article class="result-card prose">' + markdown(state.info.problem) + '</article><p class="result-footnote">想改題目或比較另一種假設，可以複製成新專案，分別保留研究成果。</p>', true);
  }
  function renderLiterature() {
    if (!state.literature) return;
    if (state.literature.error) {
      $('literature-count').textContent = '—';
      setHTML('panel-literature', '<div class="notice error">無法讀取文獻紀錄：' + escape(state.literature.error) + '</div>');
      return;
    }
    const events = state.literature.events || [];
    const papers = new Map();
    const paperKey = (paper) => paper.arxiv_id ? 'arxiv:' + paper.arxiv_id.replace(/v\d+$/, '') : paper.doi || paper.url;
    const read = new Set(events.filter((e) => e.tool === 'read_paper' && !e.error).map(paperKey));
    for (const event of events) for (const paper of event.results || []) {
      const key = paperKey(paper);
      if (key && !papers.has(key)) papers.set(key, { ...paper, at: event.at });
    }
    // A directly supplied arXiv link can be read without a preceding search.
    for (const event of events) if (event.tool === 'read_paper' && !event.error && !papers.has(paperKey(event))) {
      papers.set(paperKey(event), { ...event, title: 'arXiv:' + event.arxiv_id, source: 'arXiv' });
    }
    $('literature-count').textContent = papers.size;
    let html = '<div class="section-heading"><div><h2>查閱文獻</h2><p>Danus 會在研究前與卡關時查詢。這裡列出查詢紀錄與來源；文獻仍須經過驗證才能成為成果。</p></div></div>';
    if (!events.length) html += '<div class="inline-empty"><h2>尚未查詢文獻</h2><p>論文搜尋已備妥。開始或繼續研究後，Danus 使用搜尋工具時會自動留下紀錄。<br>簡單、自足的數學問題可能不需要查詢。</p></div>';
    for (const [key, paper] of papers) {
      const url = /^https?:\/\//i.test(paper.url || '') ? paper.url : '';
      const authors = Array.isArray(paper.authors) ? paper.authors.join('、') : '';
      html += '<article class="result-card literature-card"><div class="literature-meta"><span>' + escape(paper.source || '文獻') + (paper.year ? ' · ' + escape(paper.year) : '') + '</span><span>' + (read.has(key) ? '已擷取原文片段' : '搜尋結果') + '</span></div><h3>' + (url ? '<a href="' + escape(url) + '" target="_blank" rel="noopener noreferrer">' + escape(paper.title || url) + ' ↗</a>' : escape(paper.title)) + '</h3><p class="muted small">' + escape(authors) + '</p>' + (paper.abstract ? '<details><summary>摘要／搜尋內容</summary><div class="prose">' + escape(paper.abstract) + '</div></details>' : '') + '<p class="small muted">' + date(paper.at) + (paper.arxiv_id ? ' · arXiv:' + escape(paper.arxiv_id) : '') + (paper.doi ? ' · DOI:' + escape(paper.doi) : '') + '</p></article>';
    }
    if (events.length) html += '<details class="verification-list"><summary>查詢與讀取紀錄（最近 ' + events.length + ' 筆）</summary>' + events.map((e) => '<article class="verification-item"><p>' + date(e.at) + ' · ' + (e.tool === 'read_paper' ? '讀取原文' : '搜尋文獻') + ' · ' + escape(e.author) + '</p><strong>' + escape(e.query) + '</strong><p>' + (e.error ? '未完成：' + escape(e.error) : e.tool === 'read_paper' ? '已擷取片段，位置 ' + escape(e.offset || 0) : '找到 ' + escape(e.count || 0) + ' 筆來源') + '</p>' + (Object.keys(e.errors || {}).length ? '<p>部分來源暫時無法連線：' + escape(Object.keys(e.errors).join('、')) + '</p>' : '') + '</article>').join('') + '</details>';
    setHTML('panel-literature', html, true);
  }
  function renderTrash() {
    $('trash-count').hidden = !state.trash.length; $('trash-count').textContent = state.trash.length;
    setHTML('trash-list', state.trash.length ? state.trash.map((item) => '<article class="trash-item"><div><h3>' + escape(item.title) + '</h3><p>' + date(item.deleted_at) + ' 移到回收筒 · 成果與記錄已保留</p></div><div class="trash-actions"><button class="button" data-restore="' + escape(item.id) + '">還原</button><div class="purge-action"><button class="button danger-text" data-purge="' + escape(item.id) + '">永久刪除</button><small>無法還原</small></div></div></article>').join('') : '<div class="inline-empty"><h2>回收筒是空的</h2><p>移除的專案會出現在這裡，可隨時還原。</p></div>');
  }
  async function loadCurrent() {
    const name = state.name;
    if (!name || state.mode !== 'projects') return;
    const serial = ++state.serial;
    try {
      const [info, progress, results, literature] = await Promise.all([api(apiPath(name)), api(apiPath(name) + '/progress'), api(apiPath(name) + '/results'), api(apiPath(name) + '/literature').catch((error) => ({events: [], error: error.message}))]);
      if (serial !== state.serial || name !== state.name) return;
      Object.assign(state, { info, progress, results, literature });
      $('connection-error').hidden = true;
      renderWorkspace(); renderProgress(); renderResults(); renderProblem(); renderLiterature();
      $('sync-status').textContent = '已更新 ' + new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    } catch (error) {
      if (serial !== state.serial) return;
      $('connection-error').textContent = error.message; $('connection-error').hidden = false;
      $('sync-status').textContent = '連線中斷';
    }
  }
  let refreshTask = null;
  function refreshAll(force = false) {
    if (refreshTask) return force ? refreshTask.then(() => refreshAll()) : refreshTask;
    refreshTask = (async () => {
    try {
      const [projects, trash] = await Promise.all([api('/api/danus/projects'), api('/api/danus/trash')]);
      state.projects = projects; state.trash = trash; state.loaded = true;
      $('connection-error').hidden = true;
      if (!projects.some((p) => p.project === state.name)) {
        state.serial++;
        state.name = ''; state.info = state.progress = state.results = null;
        readRoute();
      }
      renderProjects(); renderTrash(); renderWorkspace();
      await loadCurrent();
    } catch (error) {
      $('connection-error').hidden = false; $('connection-error').textContent = error.message;
      $('sync-status').textContent = '連線中斷';
    } finally { refreshTask = null; }
    })();
    return refreshTask;
  }
  async function checkHealth() {
    try {
      await api('/api/health'); $('model-status').textContent = '本地模型已連線'; $('model-dot').className = 'status-dot green';
    } catch { $('model-status').textContent = '模型尚未連線'; $('model-dot').className = 'status-dot red'; }
  }
  function searchControls(prefix, profile) {
    const providers = state.search.providers;
    const choices = (rows, key) => '<div class="search-provider-grid">' + rows.map((p) => '<label class="search-provider"><input type="checkbox" id="' + prefix + '-' + p.id + '" data-search-group="' + key + '" value="' + escape(p.id) + '" ' + (profile[key].includes(p.id) ? 'checked' : '') + '><span><strong>' + escape(p.name) + '</strong><small>' + escape(p.description) + '</small></span></label>').join('') + '</div>';
    return '<div class="search-control" id="' + prefix + '-control" data-search-prefix="' + prefix + '"><label class="search-switch"><input type="checkbox" id="' + prefix + '-enabled" ' + (profile.enabled ? 'checked' : '') + '><span>允許網路搜尋與論文工具</span></label><fieldset class="search-source-fields"><legend>免費網頁搜尋</legend>' + choices(providers.web, 'web_engines') + '</fieldset><fieldset class="search-source-fields"><legend>論文與定理</legend>' + choices(providers.papers, 'paper_sources') + '</fieldset></div>';
  }
  function updateSearchControls(prefix) {
    const inherited = prefix === 'project-search' && $('project-search-inherit').checked;
    $(prefix + '-enabled').disabled = inherited;
    const disabled = inherited || !$(prefix + '-enabled').checked;
    $(prefix + '-control').querySelectorAll('[data-search-group]').forEach((input) => { input.disabled = disabled; });
    const test = document.querySelector('[data-test-search="' + prefix + '"]');
    if (test) test.disabled = !$(prefix + '-enabled').checked;
  }
  function collectSearchControls(prefix) {
    const selected = (group) => [...$(prefix + '-control').querySelectorAll('[data-search-group="' + group + '"]:checked')].map((input) => input.value);
    return { enabled: $(prefix + '-enabled').checked, web_engines: selected('web_engines'), paper_sources: selected('paper_sources') };
  }
  function renderSearchScope(scope) {
    const prefix = 'settings-' + scope;
    const title = scope === 'chat' ? '聊天' : 'Danus 預設';
    const description = scope === 'chat' ? '適用於 Open WebUI 的新訊息，也可在聊天上方快速開關。' : '採用「跟隨預設」的專案會使用這裡的設定。每個專案也能自行選擇。';
    rendered.delete(prefix);
    setHTML(prefix, '<form class="search-settings-card" data-search-scope="' + scope + '"><h2>' + title + '</h2><p class="muted small">' + description + '</p>' + searchControls(prefix, state.search[scope]) + '<div id="' + prefix + '-test-result" class="search-test-result" role="status"></div><p id="' + prefix + '-error" class="form-error" hidden role="alert"></p><div class="search-save-actions"><button type="button" class="button" data-test-search="' + prefix + '">測試選取來源</button><button type="submit" class="button primary">儲存設定</button></div><p class="form-hint">測試會送出「cryptography」查詢；沒有勾選的來源不會使用。</p></form>');
    updateSearchControls(prefix);
  }
  function renderChatSearchToggle() {
    if (!state.search) return;
    const enabled = state.search.chat.enabled;
    $('chat-search-toggle').textContent = '搜尋：' + (enabled ? '開啟' : '關閉');
    $('chat-search-toggle').setAttribute('aria-pressed', String(enabled));
    $('chat-search-toggle').classList.toggle('search-off', !enabled);
    $('chat-search-toggle').disabled = false;
  }
  async function loadSearchSettings() {
    try {
      state.search = await api('/api/search/settings');
      renderSearchScope('chat'); renderSearchScope('danus'); renderChatSearchToggle();
      return true;
    } catch (error) {
      setHTML('settings-chat', '<div class="notice error">' + escape(error.message) + '</div>');
      return false;
    }
  }
  async function saveSearchScope(scope, profile) {
    const result = await api('/api/search/settings/' + scope, {method: 'PUT', body: JSON.stringify(profile)});
    state.search[scope] = result.saved;
    renderSearchScope(scope); renderChatSearchToggle();
    toast(result.warning || (scope === 'chat' ? '已儲存，聊天的新訊息會套用搜尋設定。' : '已儲存，跟隨預設的 Danus 專案會套用。'));
    await loadCurrent();
  }
  async function openProjectSearch() {
    if (!state.name) return;
    if (!state.search && !await loadSearchSettings()) return;
    const name = state.name;
    try {
      const profile = await api(apiPath(name) + '/search-settings');
      $('project-search-form').dataset.project = name;
      $('project-search-title').textContent = (state.info?.title || selected()?.title || name) + ' · 搜尋';
      $('project-search-inherit').checked = profile.inherited;
      rendered.delete('project-search-controls');
      setHTML('project-search-controls', searchControls('project-search', profile));
      updateSearchControls('project-search'); errorIn('project-search-error', '');
      $('project-search-dialog').showModal();
    } catch (error) { toast(error.message); }
  }
  document.addEventListener('change', (event) => {
    const control = event.target.closest('[data-search-prefix]');
    if (control) updateSearchControls(control.dataset.searchPrefix);
    if (event.target.id === 'project-search-inherit') {
      if (event.target.checked) {
        rendered.delete('project-search-controls');
        setHTML('project-search-controls', searchControls('project-search', state.search.danus));
      }
      updateSearchControls('project-search');
    }
  });
  document.addEventListener('submit', async (event) => {
    const scope = event.target.dataset.searchScope;
    if (!scope) return;
    event.preventDefault();
    const button = event.submitter; button.disabled = true;
    try { await saveSearchScope(scope, collectSearchControls('settings-' + scope)); }
    catch (error) { errorIn('settings-' + scope + '-error', error.message); }
    finally { button.disabled = false; }
  });
  $('project-search-form').onsubmit = async (event) => {
    event.preventDefault(); const button = event.submitter; button.disabled = true;
    try {
      const profile = collectSearchControls('project-search');
      profile.inherit = $('project-search-inherit').checked;
      await api(apiPath(event.target.dataset.project) + '/search-settings', {method: 'PUT', body: JSON.stringify(profile)});
      $('project-search-dialog').close(); await loadCurrent(); toast('專案搜尋設定已儲存。');
    } catch (error) { errorIn('project-search-error', error.message); }
    finally { button.disabled = false; }
  };
  $('chat-search-toggle').onclick = async () => {
    if (!state.search) return;
    $('chat-search-toggle').disabled = true;
    try { await saveSearchScope('chat', {...state.search.chat, enabled: !state.search.chat.enabled}); }
    catch (error) { toast(error.message); }
    finally { renderChatSearchToggle(); }
  };
  $('project-search-settings').onclick = openProjectSearch;
  $('open-search-settings').onclick = () => { route('settings'); loadSearchSettings(); };
  document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-test-search]');
    if (!button) return;
    const prefix = button.dataset.testSearch;
    button.disabled = true; $(prefix + '-test-result').textContent = '正在測試選取的搜尋來源…';
    try {
      const result = await api('/api/search/test', {method: 'POST', body: JSON.stringify(collectSearchControls(prefix))});
      $(prefix + '-test-result').textContent = result.message || result.results.map((r) => (state.search.providers.web.find((p) => p.id === r.id)?.name || r.id) + '：' + (r.ok ? '可連線（' + r.count + ' 筆）' : '暫時不可用／被限流')).join('\n') || '尚未選取網頁搜尋來源。';
    } catch (error) { $(prefix + '-test-result').textContent = error.message; }
    finally { updateSearchControls(prefix); }
  });
  let toastTimer;
  function toast(message, label, action) {
    clearTimeout(toastTimer);
    $('toast-text').textContent = message; $('toast-action').hidden = !label; $('toast-action').textContent = label || '';
    $('toast-action').onclick = action ? async () => { $('toast').hidden = true; await action(); } : null;
    $('toast').hidden = false; toastTimer = setTimeout(() => { $('toast').hidden = true; }, label ? 15000 : 6000);
  }
  function errorIn(id, message) { $(id).textContent = message; $(id).hidden = !message; }
  function closeMenu() { $('project-menu').open = false; }
  function newProject(duplicate = false) {
    closeMenu();
    $('new-title').value = duplicate ? (state.info?.title || selected()?.title || '') + '（副本）' : '';
    $('new-problem').value = duplicate ? state.info?.problem || '' : '';
    $('new-search-mode').value = duplicate && state.info?.search && !state.info.search.inherited ? (state.info.search.enabled ? 'on' : 'off') : 'inherit';
    errorIn('project-form-error', ''); $('project-dialog').showModal();
  }
  async function control(mode) {
    if (state.busy || !state.name) return;
    const name = state.name;
    state.busy = true; closeMenu(); renderWorkspace();
    try {
      const stopping = mode !== 'start';
      const result = await api(apiPath(name) + (stopping ? '/stop' : '/start'), { method: 'POST', body: stopping ? JSON.stringify({ mode }) : undefined });
      toast(stopping ? result.status === 'stopped' ? '已停止，保存的成果仍保留。' : '將於本輪結束後停止；仍可按「立即停止」。' : '已開始推理，進度會自動更新。');
      if (!stopping) route('projects', name, 'progress');
      await refreshAll(true);
    } catch (error) { toast(error.message); }
    finally { state.busy = false; renderWorkspace(); }
  }
  function download() { closeMenu(); if (state.name) { const a = document.createElement('a'); a.href = apiPath() + '/export'; a.download = state.name + '.md'; a.click(); } }
  async function restore(id) {
    try {
      const result = await api('/api/danus/trash/' + encodeURIComponent(id) + '/restore', { method: 'POST' });
      await refreshAll(true); route('projects', result.name, 'results'); toast('專案已還原。');
    } catch (error) { toast(error.message); }
  }
  async function purge(id, button) {
    const item = state.trash.find((entry) => entry.id === id);
    if (!item || state.busy) return;
    const buttons = [...$('trash-list').querySelectorAll('button')];
    state.busy = true; buttons.forEach((button) => button.disabled = true);
    button.textContent = '正在刪除…';
    try {
      await api('/api/danus/trash/' + encodeURIComponent(id), { method: 'DELETE', body: JSON.stringify({ confirm: true }) });
      toast('「' + item.title + '」已永久刪除。');
      await refreshAll(true);
    } catch (error) { toast(error.message); }
    finally {
      state.busy = false; buttons.forEach((button) => button.disabled = false);
      button.textContent = '永久刪除';
    }
  }
  $('project-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (state.busy) return;
    const start = event.submitter?.value === 'start';
    state.busy = true; const buttons = [...$('project-form').querySelectorAll('button')]; buttons.forEach((b) => b.disabled = true);
    errorIn('project-form-error', '');
    try {
      const result = await api('/api/danus/projects', { method: 'POST', body: JSON.stringify({ title: $('new-title').value.trim(), problem: $('new-problem').value.trim(), start, search_mode: $('new-search-mode').value }) });
      $('project-dialog').close(); await refreshAll(true); route('projects', result.name, 'progress'); toast(start ? '專案已建立，Danus 已開始推理。' : '專案已建立，準備好時即可開始。');
    } catch (error) { errorIn('project-form-error', error.message); }
    finally { state.busy = false; buttons.forEach((b) => b.disabled = false); renderWorkspace(); }
  });
  $('rename-project').onclick = () => {
    closeMenu(); $('rename-title').value = state.info?.title || selected()?.title || '';
    $('rename-dialog').dataset.project = state.name; errorIn('rename-error', ''); $('rename-dialog').showModal();
  };
  $('rename-form').onsubmit = async (event) => {
    event.preventDefault();
    const button = event.submitter; button.disabled = true; errorIn('rename-error', '');
    try {
      await api(apiPath($('rename-dialog').dataset.project), { method: 'PATCH', body: JSON.stringify({ title: $('rename-title').value.trim() }) });
      $('rename-dialog').close(); await refreshAll(true); toast('名稱已更新。');
    } catch (error) { errorIn('rename-error', error.message); }
    finally { button.disabled = false; }
  };
  $('delete-project').onclick = () => {
    closeMenu(); const running = isRunning();
    $('delete-dialog').dataset.project = state.name;
    $('delete-description').textContent = '「' + (state.info?.title || selected()?.title) + '」' + (running ? '正在執行。確認後會先立即停止，再移到回收筒。' : '將從專案清單移除。');
    $('confirm-delete').textContent = running ? '停止並移到回收筒' : '移到回收筒';
    errorIn('delete-error', ''); $('delete-dialog').showModal();
  };
  $('confirm-delete').onclick = async () => {
    const name = $('delete-dialog').dataset.project;
    if (state.busy) return;
    state.busy = true; $('confirm-delete').disabled = true; errorIn('delete-error', '');
    try {
      const current = await api(apiPath(name));
      if (current.workers.some((w) => w.alive)) await api(apiPath(name) + '/stop', { method: 'POST', body: JSON.stringify({ mode: 'immediate' }) });
      const result = await api('/api/danus/admin/projects/' + encodeURIComponent(name), { method: 'DELETE' });
      $('delete-dialog').close(); await refreshAll(true);
      route('projects', state.projects[0]?.project || '', 'results');
      toast('已移到回收筒，成果與記錄已保留。', '復原', () => restore(result.trash_id));
    } catch (error) { errorIn('delete-error', error.message); }
    finally { state.busy = false; $('confirm-delete').disabled = false; renderWorkspace(); }
  };
  $('primary-action').onclick = () => control(isRunning() ? 'immediate' : 'start');
  $('graceful-stop').onclick = () => control('after_round');
  $('download-results').onclick = download;
  $('duplicate-project').onclick = () => newProject(true);
  $('new-project-small').onclick = $('new-project-empty').onclick = () => newProject();
  $('project-search').oninput = renderProjects;
  $('open-trash').onclick = () => route('trash');
  $('open-help').onclick = () => $('help-dialog').showModal();
  $('refresh').onclick = async () => { $('refresh').disabled = true; await Promise.all([refreshAll(), checkHealth()]); $('refresh').disabled = false; };
  $('toast-close').onclick = () => { $('toast').hidden = true; };
  $('copy-log').onclick = async () => { try { await navigator.clipboard.writeText($('raw-log').textContent); toast('工作記錄已複製。'); } catch { toast('無法自動複製，請選取記錄文字後複製。'); } };
  $('toggle-sidebar').onclick = () => {
    if (matchMedia('(max-width:760px)').matches) document.body.classList.toggle('mobile-sidebar');
    else { document.body.classList.toggle('sidebar-collapsed'); storage.set('sidebar-collapsed', String(document.body.classList.contains('sidebar-collapsed'))); }
  };
  $('sidebar-backdrop').onclick = () => document.body.classList.remove('mobile-sidebar');
  document.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (button?.dataset.project) route('projects', button.dataset.project, state.projects.find((p) => p.project === button.dataset.project)?.fact_count ? 'results' : 'progress');
    if (button?.dataset.mode) route(button.dataset.mode);
    if (button?.dataset.tab) route('projects', state.name, button.dataset.tab);
    if (button?.dataset.restore) { button.disabled = true; restore(button.dataset.restore).finally(() => { button.disabled = false; }); }
    if (button?.dataset.purge) purge(button.dataset.purge, button);
    if (button?.hasAttribute('data-close-dialog')) button.closest('dialog').close();
    if (button?.dataset.action === 'download') download();
    if (button?.dataset.action === 'progress') route('projects', state.name, 'progress');
    if (button?.dataset.action === 'duplicate') newProject(true);
    if (!event.target.closest('#project-menu')) closeMenu();
  });
  document.querySelector('.project-tabs').addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll('[data-tab]')];
    let index = tabs.findIndex((tab) => tab.dataset.tab === state.tab);
    index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    route('projects', state.name, tabs[index].dataset.tab); tabs[index].focus();
  });
  document.querySelectorAll('[data-tab]').forEach((button) => {
    button.id = 'tab-' + button.dataset.tab;
    button.setAttribute('aria-controls', 'panel-' + button.dataset.tab);
    $('panel-' + button.dataset.tab).setAttribute('aria-labelledby', button.id);
  });
  window.addEventListener('hashchange', readRoute);
  window.addEventListener('focus', () => { if (!state.busy) refreshAll(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !state.busy) refreshAll(); });
  if (storage.get('sidebar-collapsed') === 'true') document.body.classList.add('sidebar-collapsed');
  readRoute(); refreshAll(); checkHealth(); loadSearchSettings();
  setInterval(() => { if (!document.hidden && !state.busy) refreshAll(); }, 5000);
  setInterval(() => { if (!document.hidden) checkHealth(); }, 30000);
})();
