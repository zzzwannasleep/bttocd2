'use strict';

const $ = (id) => document.getElementById(id);
let FEEDS = [];

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
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add('hidden'), 3200);
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmtTime(epoch) { return epoch ? new Date(epoch * 1000).toLocaleString() : '—'; }

const KIND_LABEL = { dmhy: 'dmhy', '1lou': '1LOU', nyaa: 'Nyaa', generic: '通用', auto: '自动' };
function typeBadge(kind) {
  const k = KIND_LABEL[kind] ? kind : 'auto';
  return `<span class="type-badge type-${k}">${esc(KIND_LABEL[k])}</span>`;
}

// --------------------------------------------------------------------------- //
async function loadStatus() {
  try {
    const s = await api('/api/status');
    const b = $('target-status');
    b.textContent = '目标 CD2: ' + (s.cd2.connected ? '已连接' : '未连接');
    b.className = 'badge ' + (s.cd2.connected ? 'ok' : 'bad');
    b.title = s.cd2.message + ' @ ' + s.cd2.url;
    $('s-pushed').textContent = s.counts.pushed;
    $('s-failed').textContent = s.counts.failed;
    const a = s.anti_block;
    $('anti-info').textContent =
      `防风控：同站最小间隔 ${a.host_min_interval}s + 抖动 ${a.fetch_jitter_seconds}s · 串行抓取` +
      (a.flaresolverr ? ' · FlareSolverr✓' : '') + (a.proxy ? ' · 代理✓' : '');
  } catch (_) {}
}

async function loadFeeds() {
  FEEDS = await api('/api/feeds');
  $('s-sources').textContent = FEEDS.length;
  $('s-enabled').textContent = FEEDS.filter((f) => f.enabled).length;
  const tbody = $('feeds-table').querySelector('tbody');
  tbody.innerHTML = '';
  $('feeds-empty').classList.toggle('hidden', FEEDS.length > 0);
  for (const f of FEEDS) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><div class="cell-name">${typeBadge(f.kind)}<b>${esc(f.name)}</b></div></td>
      <td class="trunc" title="${esc(f.url)}">${esc(f.url)}</td>
      <td>${f.interval_minutes}m</td>
      <td class="trunc" title="${esc(f.target_folder)}">${esc(f.target_folder || '/')}</td>
      <td class="muted small" title="检查于 ${fmtTime(f.last_checked)}">${esc(f.last_status || '未检查')}</td>
      <td><label class="switch"><input type="checkbox" data-toggle="${f.id}" ${f.enabled ? 'checked' : ''}><span class="slider"></span></label></td>
      <td><div class="row-actions">
        <button class="ghost" data-act="check" data-id="${f.id}">检查</button>
        <button class="ghost" data-act="edit" data-id="${f.id}">编辑</button>
        <button class="danger" data-act="del" data-id="${f.id}">删除</button>
      </div></td>`;
    tbody.appendChild(tr);
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

// --------------------------------------------------------------------------- //
function syncKindUI() {
  const isOneLou = $('f-kind').value === '1lou' ||
    ($('f-kind').value === 'auto' && /1lou\./i.test($('f-url').value));
  $('onelou-hint').classList.toggle('hidden', !isOneLou);
  $('cookie-label').classList.toggle('hidden', !isOneLou);
  $('url-label').firstChild.textContent = isOneLou ? '列表页地址' : '地址';
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
  $('form-err').textContent = '';
  $('preview-out').classList.add('hidden');
  syncKindUI();
  $('modal').classList.remove('hidden');
}
function closeModal() { $('modal').classList.add('hidden'); }

function formPayload() {
  return {
    name: $('f-name').value.trim(),
    url: $('f-url').value.trim(),
    kind: $('f-kind').value,
    interval_minutes: parseInt($('f-interval').value, 10) || 30,
    target_folder: $('f-folder').value.trim() || '/',
    include_regex: $('f-include').value.trim(),
    exclude_regex: $('f-exclude').value.trim(),
    cookie: $('f-cookie').value.trim(),
    enabled: $('f-enabled').checked,
  };
}

// --------------------------------------------------------------------------- //
$('new-feed').addEventListener('click', () => openModal(null));
$('f-kind').addEventListener('change', syncKindUI);
$('f-url').addEventListener('input', syncKindUI);
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

$('feeds-table').addEventListener('change', async (e) => {
  const id = e.target.dataset.toggle; if (!id) return;
  const feed = FEEDS.find((f) => String(f.id) === id); if (!feed) return;
  try {
    await api('/api/feeds/' + id, { method: 'PUT', body: JSON.stringify({ ...feed, enabled: e.target.checked }) });
    toast(e.target.checked ? '已启用' : '已暂停'); loadFeeds(); loadStatus();
  } catch (err) { toast('操作失败: ' + err.message); e.target.checked = !e.target.checked; }
});

$('feeds-table').addEventListener('click', async (e) => {
  const btn = e.target.closest('button'); if (!btn) return;
  const id = btn.dataset.id, act = btn.dataset.act;
  if (act === 'del') {
    if (!confirm('确认删除该源？其历史记录也会清除。')) return;
    await api('/api/feeds/' + id, { method: 'DELETE' });
    toast('已删除'); loadFeeds(); loadStatus();
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
    closeModal(); toast('已保存'); loadFeeds(); loadStatus();
  } catch (err) { $('form-err').textContent = err.message; }
  finally { $('save-btn').disabled = false; }
});

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

// initial load + light polling
loadStatus(); loadFeeds(); loadItems();
setInterval(() => { loadStatus(); loadFeeds(); }, 30000);
setInterval(loadItems, 60000);
