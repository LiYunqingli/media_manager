/**
 * m3u8 嗅探器 · popup
 *
 * 纯展示层：只读 background 写进 `storage.session` 的结果，
 * 自己不监听请求、不注入页面 DOM、也不做任何网络访问。
 *
 * 数据在 storage.session 里，SW 被回收也不受影响，所以 popup 随时打开都能看到
 * 当前标签页的捕获结果。
 *
 * 「当前页面算不算被嗅探的站点」与 background 共用 `sites/index.js` 的同一份判定，
 * 两边不会再各写一个正则。
 */
import { matchSite, SITES } from './sites/index.js';
import { buildTaskText } from './task-text.js';

const STATE_KEY = 'sniffer_state_v1';

const el = {
  dot: document.getElementById('status-dot'),
  count: document.getElementById('count'),
  hint: document.getElementById('hint'),
  list: document.getElementById('list'),
  copyAll: document.getElementById('copy-all'),
  clear: document.getElementById('clear'),
  titlePanel: document.getElementById('title-panel'),
  pageTitle: document.getElementById('page-title'),
  copyTitle: document.getElementById('copy-title'),
  coverPanel: document.getElementById('cover-panel'),
  coverThumb: document.getElementById('cover-thumb'),
  coverUrl: document.getElementById('cover-url'),
  coverMore: document.getElementById('cover-more'),
  copyCover: document.getElementById('copy-cover'),
};

let tabId = -1;
let tabUrl = '';
let state = {};

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

function pad(n) {
  return String(n).padStart(2, '0');
}

function clockText(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** 从 URL 末段取个名字，取不到就回退整条 URL（仅为了一眼能认出来）。 */
function tailName(url) {
  try {
    const parts = new URL(url).pathname.split('/').filter(Boolean);
    return parts.length ? parts[parts.length - 1] : url;
  } catch {
    return url;
  }
}

/** 复制并在按钮上给个短暂反馈。 */
async function copyText(text, btn, doneText = '已复制') {
  if (!text) return;
  const original = btn.textContent;
  try {
    await navigator.clipboard.writeText(text);
    btn.textContent = doneText;
    btn.classList.add('done');
  } catch (err) {
    console.warn('[sniffer] 复制失败', err);
    btn.textContent = '复制失败';
  }
  setTimeout(() => {
    btn.textContent = original;
    btn.classList.remove('done');
  }, 1200);
}

function setHint(kind, text) {
  el.hint.textContent = text;
  el.hint.className = `hint${kind ? ` ${kind}` : ''}`;
  el.dot.className = `dot${kind ? ` ${kind}` : ''}`;
}

// ---------------------------------------------------------------------------
// 渲染
// ---------------------------------------------------------------------------

function buildItem(hit, index) {
  const li = document.createElement('li');
  li.className = 'item';

  const row = document.createElement('div');
  row.className = 'row';

  const badge = document.createElement('span');
  badge.className = 'badge';
  badge.textContent = hit.kind === 'mime' ? 'HLS' : 'M3U8';
  if (hit.kind === 'mime') {
    badge.title = 'URL 没带 .m3u8 后缀，是靠响应 Content-Type 识别出来的';
  }

  const meta = document.createElement('span');
  meta.className = 'meta';
  const bits = [`#${index + 1}`, tailName(hit.url)];
  if (hit.count > 1) bits.push(`重复 ${hit.count} 次`);
  if (hit.type) bits.push(hit.type);
  bits.push(clockText(hit.firstAt));
  meta.textContent = bits.join(' · ');

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn mini';
  btn.textContent = '复制';
  btn.addEventListener('click', () => copyText(hit.url, btn));

  row.append(badge, meta, btn);

  const url = document.createElement('div');
  url.className = 'url';
  url.textContent = hit.url;
  url.title = hit.url;

  li.append(row, url);
  return li;
}

/**
 * 渲染标题行。
 *
 * 只认 `pageTitle`（站点选择器从 DOM 里读的），不拿浏览器标签标题兜底 ——
 * 标签标题常带站点后缀（「xxx - Jable TV」），拿去当视频名得手工删，不如不显示。
 */
function renderTitle(entry) {
  const text = entry?.pageTitle || '';
  el.titlePanel.hidden = !text;
  el.pageTitle.textContent = text;
  el.pageTitle.title = text;
}

/**
 * 渲染封面区。
 *
 * 只取第一条：这个区的用途是把地址填进后端的 `cover_url`，多给几条反而要挑。
 * 图片本身也显示出来，是为了让人一眼确认「抓到的确实是这张封面」。
 */
function renderCover(entry) {
  const covers = entry?.covers || [];
  if (!covers.length) {
    el.coverPanel.hidden = true;
    el.coverThumb.removeAttribute('src');
    return;
  }

  const first = covers[0];
  el.coverPanel.hidden = false;
  el.coverThumb.hidden = false;
  el.coverThumb.src = first.url;
  el.coverUrl.textContent = first.url;
  el.coverUrl.title = first.url;

  if (covers.length > 1) {
    el.coverMore.hidden = false;
    el.coverMore.textContent = `另有 ${covers.length - 1} 条封面地址，只取第一条`;
  } else {
    el.coverMore.hidden = true;
    el.coverMore.textContent = '';
  }
}

/** 标题 + 封面一起刷，两者都来自页面上抓到的元信息，生命周期一致。 */
function renderPageInfo(entry) {
  renderTitle(entry);
  renderCover(entry);
}

function render() {
  const entry = state[tabId];
  const hits = entry?.hits || [];

  el.list.replaceChildren();
  el.count.textContent = String(hits.length);

  if (tabId < 0) {
    setHint('warn', '读不到当前标签页。');
    el.copyAll.disabled = true;
    el.clear.disabled = true;
    renderPageInfo(null);
    return;
  }

  const site = matchSite(tabUrl);
  if (!site) {
    const names = SITES.map((s) => s.name).filter(Boolean).join('、') || '（未配置）';
    setHint('warn', `当前页面不在监听范围。已配置站点：${names}。`);
    el.copyAll.disabled = true;
    el.clear.disabled = true;
    renderPageInfo(null);
    return;
  }

  renderPageInfo(entry);

  if (!hits.length) {
    setHint(
      'warn',
      '这个页面还没捕获到 m3u8。刷新一次页面或开始播放即可 —— 刚装上扩展的话，必须刷新才会生效。'
    );
    el.copyAll.disabled = true;
    el.clear.disabled = true;
    return;
  }

  setHint('ok', `${site.name} · 已捕获 ${hits.length} 条地址。`);
  el.copyAll.disabled = false;
  el.clear.disabled = false;
  hits.forEach((hit, i) => el.list.append(buildItem(hit, i)));
}

// ---------------------------------------------------------------------------
// 数据
// ---------------------------------------------------------------------------

async function refresh() {
  try {
    const got = await chrome.storage.session.get(STATE_KEY);
    state = got[STATE_KEY] || {};
  } catch (err) {
    console.warn('[sniffer] 读取状态失败', err);
    state = {};
  }
  render();
}

/**
 * 清空当前标签页的 m3u8 捕获。
 *
 * 直接写 storage.session 而不是给 SW 发消息：SW 可能正在休眠，而这里只是把
 * 数组置空，不涉及任何后台逻辑。SW 的写入是「每次事件重新读最新状态」，
 * 因此不会把这次清空又覆盖回去。
 *
 * **不动 covers** —— 封面通常只有一条、抓一次就稳定，而列表要反复清着重抓。
 * 封面想清掉刷新页面即可。
 */
async function clearCurrent() {
  if (tabId < 0) return;
  try {
    const got = await chrome.storage.session.get(STATE_KEY);
    const next = got[STATE_KEY] || {};
    if (next[tabId]) next[tabId].hits = [];
    await chrome.storage.session.set({ [STATE_KEY]: next });
  } catch (err) {
    console.warn('[sniffer] 清空失败', err);
  }
}

// ---------------------------------------------------------------------------
// 启动
// ---------------------------------------------------------------------------

el.copyAll.addEventListener('click', () => {
  const text = buildTaskText(state[tabId]);
  const count = text.split('\n').length - 1; // 去掉注释行
  copyText(text, el.copyAll, `已复制 ${count} 项`);
});

el.copyCover.addEventListener('click', () => {
  const url = state[tabId]?.covers?.[0]?.url || '';
  copyText(url, el.copyCover);
});

el.copyTitle.addEventListener('click', () => {
  const text = state[tabId]?.pageTitle || '';
  copyText(text, el.copyTitle);
});

// 图挂了（CDN 防盗链、图片已删）不影响地址本身，把预览藏掉就行
el.coverThumb.addEventListener('error', () => {
  el.coverThumb.hidden = true;
});

el.clear.addEventListener('click', clearCurrent);

// SW 抓到新地址时同步刷新界面（popup 开着也能实时看到）
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'session' && changes[STATE_KEY]) {
    state = changes[STATE_KEY].newValue || {};
    render();
  }
});

(async function init() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  tabId = tab?.id ?? -1;
  tabUrl = tab?.url || '';
  await refresh();
})();
