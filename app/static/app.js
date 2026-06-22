'use strict';

const $ = (id) => document.getElementById(id);
let FEEDS = [];
let TARGETS = [];
let TYPES = [];          // target-type metadata from /api/target-types
const typeMeta = (t) => TYPES.find((x) => x.type === t) || { fields: [], location_label: '目标位置', location_placeholder: '' };

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (res.status === 401) { location.href = '/login'; throw new Error('unauth'); }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || JSON.stringify(j); } catch (_) {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

function toast(msg) {
  const t = $('toast'); t.textContent = msg; t.classList.remove('hidden');
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add('hidden'), 3400);
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmtTime(epoch) { return epoch ? new Date(epoch * 1000).toLocaleString() : '—'; }

const KIND_LABEL = { dmhy: 'dmhy', '1lou': '1LOU', nyaa: 'Nyaa', generic: '通用', auto: '自动' };
function kindBadge(kind) {
  const k = KIND_LABEL[kind] ? kind : 'auto';
  return `<span class="type-badge type-${k}">${esc(KIND_LABEL[k])}</span>`;
}
const TTYPE_LABEL = { cd2: 'CloudDrive2', qbittorrent: 'qBittorrent', transmission: 'Transmission' };
function targetBadge(type) { return `<span class="type-badge type-${type === 'cd2' ? 'dmhy' : type === 'qbittorrent' ? '1lou' : 'nyaa'}">${esc(TTYPE_LABEL[type] || type)}</span>`; }
function targetName(id) { const t = TARGETS.find((x) => x.id === id); return t ? t.name : '—'; }

// --------------------------------------------------------------------------- //
async function loadStatus() {
  try {
    const s = await api('/api/status');
    const enabled = (s.targets || []).filter((t) => t.enabled).length;
    const b = $('target-status');
    b.textContent = `目标 ${enabled}/${(s.targets || []).length}`;
    b.className = 'badge ' + (enabled ? 'ok' : 'bad');
    $('s-pushed').textContent = s.counts.pushed;
    $('s-failed').textContent = s.counts.failed;
    $('s-targets').textContent = (s.targets || []).length;
    const a = s.anti_block;
    $('anti-info').textContent =
      `防风控：同站最小间隔 ${a.host_min_interval}s + 抖动 ${a.fetch_jitter_seconds}s · 串行抓取` +
      (a.flaresolverr ? ' · FlareSolverr✓' : '') + (a.proxy ? ' · 代理✓' : '');
  } catch (_) {}
}

// --------------------------------------------------------------------------- //
// Targets
// --------------------------------------------------------------------------- //
async function loadTargets() {
  TARGETS = await api('/api/targets');
  $('s-targets').textContent = TARGETS.length;
  const tbody = $('targets-table').querySelector('tbody');
  tbody.innerHTML = '';
  $('targets-empty').classList.toggle('hidden', TARGETS.length > 0);
  for (const t of TARGETS) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><b>${esc(t.name)}</b></td>
      <td>${targetBadge(t.type)}</td>
      <td class="trunc muted small" title="${esc(t.config.url || '')}">${esc(t.config.url || '—')}</td>
      <td><label class="switch"><input type="checkbox" data-ttoggle="${t.id}" ${t.enabled ? 'checked' : ''}><span class="slider"></span></label></td>
      <td><div class="row-actions">
        <button class="ghost" data-tact="test" data-id="${t.id}">测试</button>
        <button class="ghost" data-tact="edit" data-id="${t.id}">编辑</button>
        <button class="danger" data-tact="del" data-id="${t.id}">删除</button>
      </div></td>`;
    tbody.appendChild(tr);
  }
}

function renderTargetFields(type, config) {
  const meta = typeMeta(type);
  const box = $('t-fields');
  box.innerHTML = '';
  for (const f of meta.fields) {
    const isSecret = !!f.secret;
    const hasVal = config && (isSecret ? config['has_' + f.key] : config[f.key]);
    const val = (config && !isSecret) ? (config[f.key] || '') : '';
    const ph = isSecret && hasVal ? '已设置，留空表示不修改' : (f.placeholder || '');
    const label = document.createElement('label');
    label.innerHTML = `${esc(f.label)}<input data-cfg="${f.key}" type="${isSecret ? 'password' : 'text'}"
      value="${esc(val)}" placeholder="${esc(ph)}" autocomplete="off" />`;
    box.appendChild(label);
  }
}

function openTargetModal(target) {
  $('target-modal-title').textContent = target ? '编辑目标' : '新增目标';
  $('t-id').value = target ? target.id : '';
  $('t-name').value = target ? target.name : '';
  $('t-type').value = target ? target.type : 'cd2';
  $('t-enabled').checked = target ? !!target.enabled : true;
  $('target-err').textContent = '';
  renderTargetFields($('t-type').value, target ? target.config : null);
  $('target-modal').classList.remove('hidden');
}
function closeTargetModal() { $('target-modal').classList.add('hidden'); }

function targetPayload() {
  const config = {};
  $('t-fields').querySelectorAll('[data-cfg]').forEach((el) => {
    const v = el.value.trim();
    if (v) config[el.dataset.cfg] = v;   // blank secret omitted → backend keeps old
  });
  return { name: $('t-name').value.trim(), type: $('t-type').value, config, enabled: $('t-enabled').checked };
}

$('new-target').addEventListener('click', () => openTargetModal(null));
$('t-type').addEventListener('change', () => renderTargetFields($('t-type').value, null));
$('t-cancel').addEventListener('click', closeTargetModal);
$('target-close').addEventListener('click', closeTargetModal);
$('target-modal').addEventListener('click', (e) => { if (e.target === $('target-modal')) closeTargetModal(); });

$('t-test').addEventListener('click', async () => {
  const id = $('t-id').value;
  if (!id) { toast('请先保存目标后再测试'); return; }
  $('t-test').disabled = true; $('t-test').textContent = '测试中…';
  try {
    const r = await api('/api/targets/' + id + '/test', { method: 'POST' });
    toast(r.ok ? '连接成功: ' + r.message : '连接失败: ' + r.message);
  } catch (err) { toast('测试失败: ' + err.message); }
  finally { $('t-test').disabled = false; $('t-test').textContent = '测试连接'; }
});

$('target-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = $('t-id').value, payload = targetPayload();
  $('t-save').disabled = true;
  try {
    const saved = id
      ? await api('/api/targets/' + id, { method: 'PUT', body: JSON.stringify(payload) })
      : await api('/api/targets', { method: 'POST', body: JSON.stringify(payload) });
    if (!id) $('t-id').value = saved.id;   // keep open so user can test
    toast('已保存'); await loadTargets(); loadStatus();
    if (!id) openTargetModal(saved); else closeTargetModal();
  } catch (err) { $('target-err').textContent = err.message; }
  finally { $('t-save').disabled = false; }
});

$('targets-table').addEventListener('change', async (e) => {
  const id = e.target.dataset.ttoggle; if (!id) return;
  const t = TARGETS.find((x) => String(x.id) === id); if (!t) return;
  try {
    await api('/api/targets/' + id, { method: 'PUT', body: JSON.stringify({ name: t.name, type: t.type, config: {}, enabled: e.target.checked }) });
    toast(e.target.checked ? '已启用' : '已停用'); loadTargets(); loadStatus();
  } catch (err) { toast('操作失败: ' + err.message); e.target.checked = !e.target.checked; }
});

$('targets-table').addEventListener('click', async (e) => {
  const btn = e.target.closest('button'); if (!btn) return;
  const id = btn.dataset.id, act = btn.dataset.tact;
  if (act === 'del') {
    if (!confirm('确认删除该目标？使用它的源会变成「未配置目标」。')) return;
    await api('/api/targets/' + id, { method: 'DELETE' });
    toast('已删除'); loadTargets(); loadFeeds(); loadStatus();
  } else if (act === 'edit') {
    openTargetModal(TARGETS.find((x) => String(x.id) === id));
  } else if (act === 'test') {
    btn.disabled = true; btn.textContent = '…';
    try { const r = await api('/api/targets/' + id + '/test', { method: 'POST' }); toast(r.ok ? '连接成功: ' + r.message : '连接失败: ' + r.message); }
    catch (err) { toast('测试失败: ' + err.message); }
    finally { btn.disabled = false; btn.textContent = '测试'; }
  }
});

// --------------------------------------------------------------------------- //
// Feeds
// --------------------------------------------------------------------------- //
function posterUrl(url) { return url ? '/api/img?url=' + encodeURIComponent(url) : ''; }

async function loadFeeds() {
  FEEDS = await api('/api/feeds');
  $('s-sources').textContent = FEEDS.length;
  const grid = $('feeds-grid');
  grid.innerHTML = '';
  $('feeds-empty').classList.toggle('hidden', FEEDS.length > 0);
  for (const f of FEEDS) {
    const title = f.title_cn || f.name;
    const poster = posterUrl(f.poster);
    const tags = [];
    tags.push(`<span>${f.interval_minutes}m</span>`);
    tags.push(`<span>→ ${f.target_id ? esc(targetName(f.target_id)) : '<b style="color:var(--err)">未配置</b>'}</span>`);
    if (f.rename_enabled) tags.push(`<span>🗂 整理 S${String(f.season).padStart(2, '0')}</span>`);
    if (f.total_episodes) tags.push(`<span>共${f.total_episodes}话</span>`);
    const card = document.createElement('div');
    card.className = 'feed-card';
    card.innerHTML = `
      ${poster ? `<img class="poster" src="${poster}" alt="" onerror="this.classList.add('ph');this.removeAttribute('src');this.textContent='🎬'">`
               : `<div class="poster ph">🎬</div>`}
      <div class="fc-body">
        <div class="fc-title">${kindBadge(f.kind)}<b title="${esc(title)}">${esc(title)}</b></div>
        <div class="fc-meta">${tags.join('')}</div>
        <div class="fc-meta" title="检查于 ${fmtTime(f.last_checked)}">${esc(f.last_status || '未检查')}</div>
        <div class="fc-foot">
          <label class="switch"><input type="checkbox" data-toggle="${f.id}" ${f.enabled ? 'checked' : ''}><span class="slider"></span></label>
          <div class="fc-actions">
            <button class="ghost" data-act="check" data-id="${f.id}">检查</button>
            <button class="ghost" data-act="edit" data-id="${f.id}">编辑</button>
            <button class="danger" data-act="del" data-id="${f.id}">删除</button>
          </div>
        </div>
      </div>`;
    grid.appendChild(card);
  }
}

async function loadItems() {
  const status = $('hist-filter').value;
  let items = await api('/api/items?limit=200');
  if (status) items = items.filter((it) => it.status === status);
  const tbody = $('items-table').querySelector('tbody');
  tbody.innerHTML = '';
  $('items-empty').classList.toggle('hidden', items.length > 0);
  for (const it of items) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="muted small">${fmtTime(it.created_at)}</td>
      <td class="trunc" title="${esc(it.title)}">${esc(it.title)}</td>
      <td><span class="pill ${esc(it.status)}">${esc(it.status)}</span></td>
      <td class="trunc muted small" title="${esc(it.error || it.magnet)}">${esc(it.error || it.infohash || '')}</td>`;
    tbody.appendChild(tr);
  }
}

function syncKindUI() {
  const isOneLou = $('f-kind').value === '1lou' ||
    ($('f-kind').value === 'auto' && /1lou\./i.test($('f-url').value));
  $('onelou-hint').classList.toggle('hidden', !isOneLou);
  $('cookie-label').classList.toggle('hidden', !isOneLou);
  $('url-label').firstChild.textContent = isOneLou ? '列表页地址' : '地址';
}

function syncLocationLabel() {
  const tid = parseInt($('f-target').value, 10);
  const t = TARGETS.find((x) => x.id === tid);
  const meta = t ? typeMeta(t.type) : null;
  $('loc-label').firstChild.textContent = meta ? meta.location_label : '目标位置';
  $('f-folder').placeholder = meta ? (meta.location_placeholder || '') : '';
}

function fillTargetSelect(selectedId) {
  const sel = $('f-target');
  sel.innerHTML = TARGETS.length
    ? TARGETS.map((t) => `<option value="${t.id}">${esc(t.name)} · ${esc(TTYPE_LABEL[t.type] || t.type)}${t.enabled ? '' : '（停用）'}</option>`).join('')
    : '<option value="">请先到上方「分发目标」新增一个</option>';
  if (selectedId) sel.value = selectedId;
  syncLocationLabel();
}

function renderMetaPicked() {
  const poster = $('f-poster').value, src = $('f-metasource').value, total = $('f-total').value;
  const box = $('meta-picked');
  if (!poster && !src) { box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  $('meta-poster').src = posterUrl(poster);
  $('meta-info').innerHTML = `来源 ${esc(src || '-')}${total ? ' · 共 ' + total + ' 话' : ''}`;
}

function fillTemplatePresets() {
  const sel = $('f-tmpl-preset');
  const list = SETTINGS.rename_templates || [];
  sel.innerHTML = '<option value="">— 选择预设套用 —</option>' +
    list.map((t, i) => `<option value="${i}">${esc(t.name)}${t.name === SETTINGS.preferred_template ? ' ★首选' : ''}</option>`).join('');
}
function preferredTemplate() {
  const list = SETTINGS.rename_templates || [];
  return list.find((t) => t.name === SETTINGS.preferred_template) || list[0] || null;
}

let _previewTimer = null;
function updateNamePreview() {
  clearTimeout(_previewTimer);
  _previewTimer = setTimeout(doNamePreview, 250);
}
async function doNamePreview() {
  const el = $('name-preview');
  if (!$('f-rename').checked) { el.classList.add('hidden'); return; }
  el.classList.remove('hidden');
  const body = {
    template: $('f-template').value.trim(),
    item_title: $('f-sample').value.trim(),
    title: $('f-name').value.trim(),
    title_cn: $('f-title').value.trim(),
    year: $('f-year').value.trim(),
    season: parseInt($('f-season').value, 10) || 1,
    episode_offset: parseInt($('f-offset').value, 10) || 0,
    meta_source: $('f-metasource').value,
    meta_id: $('f-metaid').value,
    sample_episode: 1,
  };
  try {
    const r = await api('/api/name-preview', { method: 'POST', body: JSON.stringify(body) });
    const root = ($('f-library').value || SETTINGS.library_root || '<媒体库根>').replace(/\/$/, '');
    el.innerHTML = `预览：<code>${esc(root)}/${esc(r.full)}</code>`;
  } catch (err) { el.innerHTML = '<span class="error">预览失败: ' + esc(err.message) + '</span>'; }
}

function openModal(feed) {
  $('modal-title').textContent = feed ? '编辑源' : '新增源';
  $('feed-id').value = feed ? feed.id : '';
  $('f-name').value = feed ? feed.name : '';
  $('f-url').value = feed ? feed.url : '';
  $('f-kind').value = feed ? feed.kind : 'auto';
  $('f-interval').value = feed ? feed.interval_minutes : 30;
  $('f-folder').value = feed ? feed.target_folder : '';
  $('f-include').value = feed ? feed.include_regex : '';
  $('f-exclude').value = feed ? feed.exclude_regex : '';
  $('f-cookie').value = feed ? (feed.cookie || '') : '';
  $('f-enabled').checked = feed ? !!feed.enabled : true;
  // metadata
  $('f-title').value = feed ? (feed.title_cn || '') : '';
  $('f-year').value = feed ? (feed.year || '') : '';
  $('f-season').value = feed ? (feed.season ?? 1) : 1;
  $('f-offset').value = feed ? (feed.episode_offset ?? 0) : 0;
  $('f-library').value = feed ? (feed.library_path || '') : '';
  $('f-rename').checked = feed ? !!feed.rename_enabled : false;
  const pref = preferredTemplate();
  $('f-template').value = feed ? (feed.rename_template || '') : (pref ? pref.template : '');
  $('f-poster').value = feed ? (feed.poster || '') : '';
  $('f-metasource').value = feed ? (feed.meta_source || '') : '';
  $('f-metaid').value = feed ? (feed.meta_id || '') : '';
  $('f-total').value = feed ? (feed.total_episodes || '') : '';
  $('f-scrape-kw').value = feed ? (feed.title_cn || feed.name || '') : '';
  $('f-sample').value = '';
  $('scrape-results').innerHTML = '';
  renderMetaPicked();
  fillTemplatePresets();
  fillTargetSelect(feed ? feed.target_id : (TARGETS[0] && TARGETS[0].id));
  $('form-err').textContent = '';
  $('preview-out').classList.add('hidden');
  syncKindUI(); updateNamePreview();
  $('modal').classList.remove('hidden');
}
function closeModal() { $('modal').classList.add('hidden'); }

function formPayload() {
  const tid = parseInt($('f-target').value, 10);
  return {
    name: $('f-name').value.trim(),
    url: $('f-url').value.trim(),
    kind: $('f-kind').value,
    interval_minutes: parseInt($('f-interval').value, 10) || 30,
    target_id: Number.isFinite(tid) ? tid : null,
    target_folder: $('f-folder').value.trim() || '/',
    include_regex: $('f-include').value.trim(),
    exclude_regex: $('f-exclude').value.trim(),
    cookie: $('f-cookie').value.trim(),
    enabled: $('f-enabled').checked,
    title_cn: $('f-title').value.trim(),
    year: $('f-year').value.trim(),
    season: parseInt($('f-season').value, 10) || 1,
    episode_offset: parseInt($('f-offset').value, 10) || 0,
    total_episodes: parseInt($('f-total').value, 10) || 0,
    poster: $('f-poster').value,
    meta_source: $('f-metasource').value,
    meta_id: $('f-metaid').value,
    library_path: $('f-library').value.trim(),
    rename_enabled: $('f-rename').checked,
    rename_template: $('f-template').value.trim(),
  };
}

// Scrape metadata
$('f-scrape-btn').addEventListener('click', async () => {
  const kw = $('f-scrape-kw').value.trim() || $('f-name').value.trim();
  if (!kw) { toast('请输入要搜索的名称'); return; }
  const box = $('scrape-results');
  box.innerHTML = '<span class="muted small">刮削中…</span>';
  try {
    const results = await api('/api/meta/search', { method: 'POST', body: JSON.stringify({ keyword: kw }) });
    if (!results.length) { box.innerHTML = '<span class="muted small">没有匹配结果</span>'; return; }
    box.innerHTML = '';
    for (const r of results) {
      const el = document.createElement('div');
      el.className = 'scrape-cand';
      el.innerHTML = `<img src="${posterUrl(r.poster)}" onerror="this.style.visibility='hidden'"><div class="sc-t" title="${esc(r.title)} ${esc(r.year)}">${esc(r.title)}</div><div class="sc-t muted">${esc(r.year)}</div>`;
      el.addEventListener('click', () => {
        $('f-title').value = r.title || '';
        $('f-year').value = r.year || '';
        $('f-poster').value = r.poster || '';
        $('f-metasource').value = r.source || '';
        $('f-metaid').value = r.id || '';
        $('f-total').value = r.total_episodes || '';
        if (!$('f-rename').checked) $('f-rename').checked = true;
        renderMetaPicked(); updateNamePreview();
        toast('已选用：' + r.title);
      });
      box.appendChild(el);
    }
  } catch (err) { box.innerHTML = '<span class="error">' + esc(err.message) + '</span>'; }
});
['f-title', 'f-year', 'f-season', 'f-offset', 'f-library', 'f-template', 'f-sample'].forEach((id) =>
  $(id).addEventListener('input', updateNamePreview));
$('f-rename').addEventListener('change', updateNamePreview);
$('f-tmpl-preset').addEventListener('change', (e) => {
  const list = SETTINGS.rename_templates || [];
  const t = list[parseInt(e.target.value, 10)];
  if (t) { $('f-template').value = t.template; if (!$('f-rename').checked) $('f-rename').checked = true; updateNamePreview(); }
});

// --------------------------------------------------------------------------- //
$('new-feed').addEventListener('click', () => openModal(null));
$('f-kind').addEventListener('change', syncKindUI);
$('f-url').addEventListener('input', syncKindUI);
$('f-target').addEventListener('change', syncLocationLabel);
$('cancel-btn').addEventListener('click', closeModal);
$('modal-close').addEventListener('click', closeModal);
$('modal').addEventListener('click', (e) => { if (e.target === $('modal')) closeModal(); });
$('logout').addEventListener('click', async () => { await api('/api/logout', { method: 'POST' }); location.href = '/login'; });
$('refresh-items').addEventListener('click', loadItems);
$('hist-filter').addEventListener('change', loadItems);

$('check-all').addEventListener('click', async (e) => {
  const enabled = FEEDS.filter((f) => f.enabled);
  if (!enabled.length) { toast('没有启用的源'); return; }
  e.target.disabled = true; e.target.textContent = '检查中…';
  let pushed = 0, failed = 0;
  for (const f of enabled) {
    try { const r = await api('/api/feeds/' + f.id + '/check', { method: 'POST' }); pushed += r.pushed; failed += r.failed; }
    catch (_) { failed++; }
  }
  e.target.disabled = false; e.target.textContent = '检查全部';
  toast(`完成：分发 ${pushed} · 失败 ${failed}`);
  loadFeeds(); loadItems(); loadStatus();
});

$('feeds-grid').addEventListener('change', async (e) => {
  const id = e.target.dataset.toggle; if (!id) return;
  const feed = FEEDS.find((f) => String(f.id) === id); if (!feed) return;
  try {
    await api('/api/feeds/' + id, { method: 'PUT', body: JSON.stringify({ ...feed, enabled: e.target.checked }) });
    toast(e.target.checked ? '已启用' : '已暂停'); loadFeeds();
  } catch (err) { toast('操作失败: ' + err.message); e.target.checked = !e.target.checked; }
});

$('feeds-grid').addEventListener('click', async (e) => {
  const btn = e.target.closest('button'); if (!btn) return;
  const id = btn.dataset.id, act = btn.dataset.act;
  if (act === 'del') {
    if (!confirm('确认删除该源？其历史记录也会清除。')) return;
    await api('/api/feeds/' + id, { method: 'DELETE' });
    toast('已删除'); loadFeeds();
  } else if (act === 'edit') {
    openModal(FEEDS.find((f) => String(f.id) === id));
  } else if (act === 'check') {
    btn.disabled = true; btn.textContent = '检查中…';
    try {
      const r = await api('/api/feeds/' + id + '/check', { method: 'POST' });
      toast(`新增 ${r.new} · 分发 ${r.pushed} · 失败 ${r.failed}` + (r.error ? ` · ${r.error}` : ''));
      loadFeeds(); loadItems(); loadStatus();
    } catch (err) { toast('检查失败: ' + err.message); }
    finally { btn.disabled = false; btn.textContent = '检查'; }
  }
});

$('preview-btn').addEventListener('click', async () => {
  const id = $('feed-id').value;
  if (!id) { toast('请先保存源后再预览'); return; }
  const out = $('preview-out'); out.classList.remove('hidden'); out.textContent = '解析中…';
  try {
    const r = await api('/api/feeds/' + id + '/preview', { method: 'POST' });
    out.textContent = `匹配 ${r.found} 条，其中新条目 ${r.new} 条（预览不分发）` + (r.error ? `\n错误: ${r.error}` : '');
  } catch (err) { out.textContent = '预览失败: ' + err.message; }
});

$('feed-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = $('feed-id').value, payload = formPayload();
  $('save-btn').disabled = true;
  try {
    if (id) await api('/api/feeds/' + id, { method: 'PUT', body: JSON.stringify(payload) });
    else await api('/api/feeds', { method: 'POST', body: JSON.stringify(payload) });
    closeModal(); toast('已保存'); loadFeeds();
  } catch (err) { $('form-err').textContent = err.message; }
  finally { $('save-btn').disabled = false; }
});

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeModal(); closeTargetModal(); } });

// --------------------------------------------------------------------------- //
// Navigation / views
// --------------------------------------------------------------------------- //
let settingsLoaded = false;
function switchView(view) {
  document.querySelectorAll('.nav-item').forEach((n) => n.classList.toggle('active', n.dataset.view === view));
  document.querySelectorAll('.view').forEach((v) => v.classList.toggle('hidden', v.id !== 'view-' + view));
  if (view === 'history') loadItems();
  if (view === 'settings' && !settingsLoaded) loadSettings();
}
$('nav').addEventListener('click', (e) => {
  const item = e.target.closest('.nav-item'); if (!item) return;
  switchView(item.dataset.view);
});

// --------------------------------------------------------------------------- //
// Settings
// --------------------------------------------------------------------------- //
const SET_MAP = {
  'set-host': 'host_min_interval', 'set-jitter': 'fetch_jitter_seconds',
  'set-interval': 'default_interval_minutes', 'set-maxitems': 'max_items_per_run',
  'set-proxy': 'http_proxy', 'set-flaresolverr': 'flaresolverr_url',
  'set-notify': 'notify_enabled', 'set-onsuccess': 'notify_on_success', 'set-onfailure': 'notify_on_failure',
  'set-tg-token': 'telegram_bot_token', 'set-tg-chat': 'telegram_chat_id',
  'set-bark': 'bark_url', 'set-serverchan': 'serverchan_key', 'set-webhook': 'webhook_url',
  'set-metasource': 'meta_source', 'set-tmdbkey': 'tmdb_api_key', 'set-library': 'library_root',
  'set-deftmpl': 'default_rename_template',
};
let SETTINGS = {};

async function loadSettings() {
  const s = await api('/api/settings');
  SETTINGS = s;
  for (const [id, key] of Object.entries(SET_MAP)) {
    const el = $(id); if (!el) continue;
    if (el.type === 'checkbox') el.checked = !!s[key];
    else el.value = s[key] ?? '';
  }
  renderTmplRows(s.rename_templates || [], s.preferred_template);
  renderTagRows(s.rename_tags || []);
  settingsLoaded = true;
}
function collectSettings() {
  const out = {};
  for (const [id, key] of Object.entries(SET_MAP)) {
    const el = $(id); if (!el) continue;
    out[key] = el.type === 'checkbox' ? el.checked : (el.type === 'number' ? parseInt(el.value, 10) || 0 : el.value.trim());
  }
  return out;
}
async function saveSettings(btn, extra = {}) {
  btn.disabled = true;
  try {
    SETTINGS = await api('/api/settings', { method: 'PUT', body: JSON.stringify({ ...collectSettings(), ...extra }) });
    toast('设置已保存'); loadStatus();
  } catch (err) { toast('保存失败: ' + err.message); }
  finally { btn.disabled = false; }
}

// ---- template-preset rows ----
function tmplRow(t = { name: '', template: '' }, preferred = false) {
  const div = document.createElement('div');
  div.className = 'tmpl-row';
  div.innerHTML = `<span class="pref-wrap" title="设为首选"><input type="radio" name="preftmpl" ${preferred ? 'checked' : ''}></span>
    <input class="t-name" placeholder="模板名" value="${esc(t.name)}">
    <input class="t-tmpl" placeholder="\${title} (\${year})/Season \${seasonFormat}/..." value="${esc(t.template)}">
    <button type="button" class="row-del">✕</button>`;
  div.querySelector('.row-del').addEventListener('click', () => div.remove());
  return div;
}
function renderTmplRows(list, preferred) {
  const box = $('tmpl-list'); box.innerHTML = '';
  list.forEach((t) => box.appendChild(tmplRow(t, t.name === preferred)));
  // ensure at least one radio is selected
  if (!box.querySelector('input[name="preftmpl"]:checked')) {
    const first = box.querySelector('input[name="preftmpl"]'); if (first) first.checked = true;
  }
}
function collectTmpls() {
  return [...$('tmpl-list').querySelectorAll('.tmpl-row')].map((r) => ({
    name: r.querySelector('.t-name').value.trim(), template: r.querySelector('.t-tmpl').value.trim(),
  })).filter((t) => t.name && t.template);
}
function collectPreferred() {
  const rows = [...$('tmpl-list').querySelectorAll('.tmpl-row')];
  for (const r of rows) {
    if (r.querySelector('input[name="preftmpl"]').checked) return r.querySelector('.t-name').value.trim();
  }
  return '';
}
// ---- keyword-rule rows ----
function tagRow(t = { var: '', label: '', patterns: [] }) {
  const div = document.createElement('div');
  div.className = 'tag-row';
  div.innerHTML = `<input class="g-var" placeholder="lang" value="${esc(t.var)}">
    <input class="g-label" placeholder="简体中文" value="${esc(t.label)}">
    <input class="g-pat" placeholder="CHS,简体,GB" value="${esc((t.patterns || []).join(','))}">
    <button type="button" class="row-del">✕</button>`;
  div.querySelector('.row-del').addEventListener('click', () => div.remove());
  return div;
}
function renderTagRows(list) { const box = $('tag-list'); box.innerHTML = ''; list.forEach((t) => box.appendChild(tagRow(t))); }
function collectTags() {
  return [...$('tag-list').querySelectorAll('.tag-row')].map((r) => ({
    var: r.querySelector('.g-var').value.trim(),
    label: r.querySelector('.g-label').value.trim(),
    patterns: r.querySelector('.g-pat').value.split(',').map((x) => x.trim()).filter(Boolean),
  })).filter((t) => t.var && t.label && t.patterns.length);
}

$('tmpl-add').addEventListener('click', () => $('tmpl-list').appendChild(tmplRow()));
$('tag-add').addEventListener('click', () => $('tag-list').appendChild(tagRow()));
$('set-save-crawl').addEventListener('click', (e) => saveSettings(e.target));
$('set-save-notify').addEventListener('click', (e) => saveSettings(e.target));
$('set-save-meta').addEventListener('click', (e) => saveSettings(e.target));
$('set-save-rename').addEventListener('click', (e) =>
  saveSettings(e.target, {
    rename_templates: collectTmpls(), rename_tags: collectTags(),
    preferred_template: collectPreferred(),
  }));

// ---- import / export (share template sets) ----
$('rename-export').addEventListener('click', () => {
  const data = {
    default_rename_template: $('set-deftmpl').value.trim(),
    preferred_template: collectPreferred(),
    rename_templates: collectTmpls(),
    rename_tags: collectTags(),
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'bt2cd2-rename-templates.json';
  a.click(); URL.revokeObjectURL(a.href);
  toast('已导出，可分享该 JSON');
});
$('rename-import').addEventListener('click', () => $('rename-file').click());
$('rename-file').addEventListener('change', async (e) => {
  const file = e.target.files[0]; if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    if (Array.isArray(data.rename_templates)) renderTmplRows(data.rename_templates, data.preferred_template);
    if (Array.isArray(data.rename_tags)) renderTagRows(data.rename_tags);
    if (data.default_rename_template) $('set-deftmpl').value = data.default_rename_template;
    toast('已导入，点「保存重命名设置」生效');
  } catch (err) { toast('导入失败：JSON 格式错误'); }
  finally { e.target.value = ''; }
});
$('set-test').addEventListener('click', async (e) => {
  e.target.disabled = true;
  try { await api('/api/settings', { method: 'PUT', body: JSON.stringify(collectSettings()) }); const r = await api('/api/settings/test-notify', { method: 'POST' }); toast(r.message); }
  catch (err) { toast('测试失败: ' + err.message); }
  finally { e.target.disabled = false; }
});

// initial load + light polling
(async () => {
  try { TYPES = await api('/api/target-types'); } catch (_) {}
  try { await loadSettings(); } catch (_) {}
  await loadTargets();
  loadStatus(); loadFeeds(); loadItems();
})();
setInterval(() => { loadStatus(); loadTargets(); loadFeeds(); }, 30000);
setInterval(() => { if (!$('view-history').classList.contains('hidden')) loadItems(); }, 60000);
