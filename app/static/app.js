'use strict';

const $ = (id) => document.getElementById(id);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (res.status === 401) { location.href = '/login'; throw new Error('unauth'); }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || JSON.stringify(j); } catch (_) {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  setTimeout(() => t.classList.add('hidden'), 3000);
}

function esc(s) {
  return String(s || '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function fmtTime(epoch) {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleString();
}

// --------------------------------------------------------------------------- //
// Status + stats
// --------------------------------------------------------------------------- //
async function loadStatus() {
  try {
    const s = await api('/api/status');
    const badge = $('cd2-status');
    badge.textContent = 'CD2: ' + (s.cd2.connected ? '已连接' : '未连接');
    badge.className = 'badge ' + (s.cd2.connected ? 'ok' : 'bad');
    badge.title = s.cd2.message + ' @ ' + s.cd2.url;
    $('stats').textContent =
      `订阅 ${s.counts.feeds} · 已推送 ${s.counts.pushed} · 失败 ${s.counts.failed}` +
      ` · 同站最小间隔 ${s.anti_block.host_min_interval}s + 抖动 ${s.anti_block.fetch_jitter_seconds}s` +
      (s.anti_block.flaresolverr ? ' · FlareSolverr✓' : '') +
      (s.anti_block.proxy ? ' · 代理✓' : '');
  } catch (e) { /* ignore */ }
}

// --------------------------------------------------------------------------- //
// Feeds
// --------------------------------------------------------------------------- //
async function loadFeeds() {
  const feeds = await api('/api/feeds');
  const tbody = $('feeds-table').querySelector('tbody');
  tbody.innerHTML = '';
  for (const f of feeds) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${esc(f.name)}</td>
      <td class="trunc" title="${esc(f.url)}">${esc(f.url)}</td>
      <td>${f.interval_minutes}m</td>
      <td class="trunc" title="${esc(f.target_folder)}">${esc(f.target_folder)}</td>
      <td class="muted small" title="检查于 ${fmtTime(f.last_checked)}">${esc(f.last_status || '—')}</td>
      <td>${f.enabled ? '✅' : '⏸️'}</td>
      <td><div class="actions">
        <button class="ghost" data-act="check" data-id="${f.id}">立即检查</button>
        <button class="ghost" data-act="edit" data-id="${f.id}">编辑</button>
        <button class="ghost danger" data-act="del" data-id="${f.id}">删除</button>
      </div></td>`;
    tbody.appendChild(tr);
  }
}

async function loadItems() {
  const items = await api('/api/items?limit=200');
  const tbody = $('items-table').querySelector('tbody');
  tbody.innerHTML = '';
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
// Modal
// --------------------------------------------------------------------------- //
function syncKindUI() {
  const isOneLou = $('f-kind').value === '1lou' ||
    ($('f-kind').value === 'auto' && /1lou\./i.test($('f-url').value));
  $('onelou-hint').classList.toggle('hidden', !isOneLou);
  $('cookie-label').classList.toggle('hidden', !isOneLou);
  $('url-label').firstChild.textContent = isOneLou ? '列表页地址' : '地址';
}

function openModal(feed) {
  $('modal-title').textContent = feed ? '编辑订阅' : '新增订阅';
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
// Events
// --------------------------------------------------------------------------- //
$('new-feed').addEventListener('click', () => openModal(null));
$('f-kind').addEventListener('change', syncKindUI);
$('f-url').addEventListener('input', syncKindUI);
$('cancel-btn').addEventListener('click', closeModal);
$('logout').addEventListener('click', async () => { await api('/api/logout', { method: 'POST' }); location.href = '/login'; });
$('refresh-items').addEventListener('click', loadItems);

$('feeds-table').addEventListener('click', async (e) => {
  const btn = e.target.closest('button'); if (!btn) return;
  const id = btn.dataset.id; const act = btn.dataset.act;
  if (act === 'del') {
    if (!confirm('确认删除该订阅？历史记录也会清除。')) return;
    await api('/api/feeds/' + id, { method: 'DELETE' });
    toast('已删除'); loadFeeds(); loadStatus();
  } else if (act === 'edit') {
    const feeds = await api('/api/feeds');
    openModal(feeds.find((f) => String(f.id) === id));
  } else if (act === 'check') {
    btn.disabled = true; btn.textContent = '检查中…';
    try {
      const r = await api('/api/feeds/' + id + '/check', { method: 'POST' });
      toast(`新增 ${r.new} · 推送 ${r.pushed} · 失败 ${r.failed}` + (r.error ? ` · ${r.error}` : ''));
      loadFeeds(); loadItems(); loadStatus();
    } catch (err) { toast('检查失败: ' + err.message); }
    finally { btn.disabled = false; btn.textContent = '立即检查'; }
  }
});

$('preview-btn').addEventListener('click', async () => {
  const id = $('feed-id').value;
  if (!id) { toast('请先保存订阅后再预览'); return; }
  try {
    const r = await api('/api/feeds/' + id + '/preview', { method: 'POST' });
    const out = $('preview-out');
    out.textContent = `匹配 ${r.found} 条，其中新条目 ${r.new} 条（预览不会推送）` + (r.error ? `\n错误: ${r.error}` : '');
    out.classList.remove('hidden');
  } catch (err) { toast('预览失败: ' + err.message); }
});

$('feed-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = $('feed-id').value;
  const payload = formPayload();
  try {
    if (id) await api('/api/feeds/' + id, { method: 'PUT', body: JSON.stringify(payload) });
    else await api('/api/feeds', { method: 'POST', body: JSON.stringify(payload) });
    closeModal(); toast('已保存'); loadFeeds(); loadStatus();
  } catch (err) { $('form-err').textContent = err.message; }
});

// initial load + light polling
loadStatus(); loadFeeds(); loadItems();
setInterval(() => { loadStatus(); loadFeeds(); }, 30000);
setInterval(loadItems, 60000);
