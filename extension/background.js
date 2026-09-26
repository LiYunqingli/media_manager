/**
 * m3u8 嗅探器 · background service worker
 *
 * 职责很窄：**只在命中目标正则的页面上**，把该页发出的 m3u8 / 封面图请求地址
 * 收集起来，并在页面加载完成后读出视频标题。其余站点一律丢弃，不在本地留任何痕迹。
 *
 * 四条捕获途径：
 *   1. onBeforeRequest   —— URL 以 .m3u8 结尾（绝大多数情况，master 与 media 列表都算）
 *   2. onHeadersReceived —— 响应 Content-Type 是 HLS 的 MIME，用于 URL 不带后缀的变体
 *   3. onBeforeRequest   —— 图片请求命中站点规则里的 `covers` 模式（封面图）
 *   4. tabs.onUpdated    —— status=complete 时注入脚本，按站点的 `selectors` 读页面 DOM
 *
 * MV3 的 service worker 会被随时回收，因此有两条硬性约束：
 *   · 状态一律放 `chrome.storage.session`，**不能放模块级变量** ——
 *     那是上一次会话的残影，表现为「过一会儿抓到的链接全没了」；
 *   · 多个 webRequest 事件几乎同时到达，读-改-写必须串行（见 withState）。
 */

// ---------------------------------------------------------------------------
// 配置
// ---------------------------------------------------------------------------

/**
 * 「嗅探哪些站点」不在这里定义，全部收在 `sites/` 目录下 —— 见 `sites/index.js`。
 * 加站点、改封面规则都只改配置，不用碰这个文件。
 */
import { matchSite, matchCover } from './sites/index.js';

/** URL 直判：以 .m3u8 结尾，允许带 query / hash。 */
const M3U8_URL = /\.m3u8(?:[?#]|$)/i;

/** 响应头兜底：URL 没后缀但 Content-Type 是 HLS 的那些变体。 */
const HLS_MIME = /(?:application|audio|video)\/(?:vnd\.apple\.mpegurl|x-mpegurl|mpegurl)/i;

/**
 * 封面预筛：先按扩展名做一次极廉价判断，命中了才去读存储比对站点规则。
 *
 * 页面上的 js / css / 接口请求远多于图片，这一层能让绝大多数请求在**不碰
 * storage.session** 的情况下直接短路掉。
 */
const IMAGE_EXT = /\.(?:jpe?g|png|webp|avif)(?:[?#]|$)/i;

/** 单个标签页最多留多少条 m3u8。 */
const MAX_HITS = 60;

/** 封面通常只有一两条，上限给小一点。 */
const MAX_COVERS = 10;

/** storage.session 里的状态键。带版本号，日后改结构好区分旧数据。 */
const STATE_KEY = 'sniffer_state_v1';

// ---------------------------------------------------------------------------
// 状态：读写串行化
// ---------------------------------------------------------------------------
// state = {
//   [tabId]: {
//     url, title, pageTitle, siteId, siteName, startedAt,
//     hits:   [ { url, kind, type, initiator, firstAt, lastAt, count } ],
//     covers: [ { url, type, firstAt, lastAt, count } ]
//   }
// }
//
// title     —— 浏览器标签页标题（tabs.onUpdated 给什么就是什么）
// pageTitle —— 站点 `selectors.title` 从 DOM 里读出来的标题，权威性更高
//
// 为什么不用 Map 缓存：SW 被回收后 Map 就没了。全部走 storage.session，
// 代价是每次事件一次异步读写，收益是行为在 SW 休眠前后完全一致。

let queue = Promise.resolve();

/**
 * 串行执行「读状态 → 改状态 → 写状态」。
 *
 * 直接并发调 `storage.session.set` 会互相覆盖：m3u8 的 master 与 media 两条请求
 * 常常在同一毫秒内到达，后写的那次会把先写的整份 state 盖掉，表现为「只抓到一条」。
 */
function withState(mutator) {
  queue = queue
    .then(async () => {
      let state = {};
      try {
        const got = await chrome.storage.session.get(STATE_KEY);
        state = got[STATE_KEY] || {};
      } catch (err) {
        console.warn('[sniffer] 读取状态失败', err);
        return;
      }
      await mutator(state);
      try {
        await chrome.storage.session.set({ [STATE_KEY]: state });
      } catch (err) {
        console.warn('[sniffer] 写入状态失败', err);
      }
    })
    .catch((err) => console.error('[sniffer] 状态队列异常', err));
  return queue;
}

/**
 * 页面是否属于被嗅探的站点。判定逻辑全在 `sites/index.js`，
 * 这里只是取个名字。
 */
function matchWatchSite(url) {
  return matchSite(url);
}

function emptyEntry(url, title, site) {
  return {
    url: url || '',
    title: title || '',
    pageTitle: '',
    siteId: site?.id || '',
    siteName: site?.name || '',
    startedAt: Date.now(),
    hits: [],
    covers: [],
  };
}

// ---------------------------------------------------------------------------
// 标签页生命周期：决定「哪些标签页需要被监听」
// ---------------------------------------------------------------------------

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  // 只关心「导航开始 / 导航结束 / URL 变化」，浏览器标题之类的噪声不理会。
  // 注意 loading 与 complete 都要放行：前者建条目，后者是读 DOM 的时机。
  const navigating = changeInfo.status === 'loading' || changeInfo.status === 'complete';
  if (!navigating && !changeInfo.url) return;
  const url = tab.url || '';
  const site = matchWatchSite(url);

  withState((state) => {
    if (!site) {
      // 离开目标页就销毁条目：不在本地留下其它站点的任何数据
      delete state[tabId];
      return;
    }
    const prev = state[tabId];
    if (!prev || prev.url !== url) {
      // 换了页面地址：旧捕获无效
      state[tabId] = emptyEntry(url, tab.title, site);
      return;
    }
    if (changeInfo.status === 'loading') {
      // 同一地址刷新：旧捕获同样失效，否则会把上一轮的结果和这一轮混在一起
      prev.hits = [];
      prev.covers = [];
      prev.pageTitle = '';
      prev.startedAt = Date.now();
    }
  });

  // 页面加载完成才去读 DOM —— loading 阶段元素还没解析出来
  if (changeInfo.status === 'complete' && site) {
    capturePageInfo(tabId, url, site);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  withState((state) => {
    delete state[tabId];
  });
});

// ---------------------------------------------------------------------------
// 捕获
// ---------------------------------------------------------------------------

function recordHit(tabId, hit) {
  return withState((state) => {
    const entry = state[tabId];
    // 条目不存在 = 这个标签页不是被嗅探的站点（或还没导航过）→ 直接丢弃
    if (!entry || !matchWatchSite(entry.url)) return;

    const exist = entry.hits.find((h) => h.url === hit.url);
    if (exist) {
      exist.lastAt = hit.at;
      exist.count += 1;
      // URL 判断降级为 MIME 判断时，标记要跟着升级，便于排查
      if (hit.kind === 'mime') exist.kind = 'mime';
      return;
    }

    entry.hits.unshift({
      url: hit.url,
      kind: hit.kind,
      type: hit.type || '',
      initiator: hit.initiator || '',
      firstAt: hit.at,
      lastAt: hit.at,
      count: 1,
    });
    if (entry.hits.length > MAX_HITS) entry.hits.length = MAX_HITS;
  });
}

/**
 * 记录封面图。
 *
 * 与 recordHit 分成两个数组、两个函数，是因为二者的用途完全不同：
 * hits 要全部列出来供挑选，covers 只取一条填进后端的 `cover_url`，
 * 且判定规则（`covers` 模式 vs `.m3u8` 后缀）毫无重叠。
 */
function recordCover(tabId, cover) {
  return withState((state) => {
    const entry = state[tabId];
    if (!entry) return;
    const site = matchWatchSite(entry.url);
    if (!site) return;
    // 光有图片扩展名还不够 —— 站点的 logo、缩略图列表都会命中这条，
    // 必须再对上站点自己的 covers 模式才算。
    if (!matchCover(cover.url, site)) return;

    const exist = entry.covers.find((c) => c.url === cover.url);
    if (exist) {
      exist.lastAt = cover.at;
      exist.count += 1;
      return;
    }

    if (!Array.isArray(entry.covers)) entry.covers = [];
    entry.covers.unshift({
      url: cover.url,
      type: cover.type || '',
      firstAt: cover.at,
      lastAt: cover.at,
      count: 1,
    });
    if (entry.covers.length > MAX_COVERS) entry.covers.length = MAX_COVERS;
  });
}

// ---------------------------------------------------------------------------
// 页面 DOM 信息（标题）
// ---------------------------------------------------------------------------
// service worker 没有 DOM，只能把脚本注入到页面里去执行。
//
// 用 `func` + `args` 这种内联形式，而不是单独的 content script 文件：
// content script 不支持 ESM，**没法 import 站点规则**，那样选择器就得在
// 两处维护；而内联注入可以把选择器当参数传进去，规则仍然只有 `sites/` 一份。
//
// 代价是 manifest 里要开 `scripting` 权限。

/** 元素最长等多久（毫秒）。前端渲染的站点在 complete 时 DOM 还没长出来。 */
const PAGE_INFO_WAIT = 5000;

async function capturePageInfo(tabId, url, site) {
  const selector = site?.selectors?.title;
  if (!selector) return; // 站点没配选择器 → 连脚本都不注入

  let text = '';
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      args: [selector, PAGE_INFO_WAIT],
      // 注意：这个函数会被序列化后送进页面执行，**不能引用外部作用域的任何变量**
      func: (sel, wait) =>
        new Promise((resolve) => {
          const pick = () => {
            const el = document.querySelector(sel);
            const value = (el?.textContent || '').trim();
            if (!value) return false;
            resolve(value);
            return true;
          };
          if (pick()) return;

          // 首次没读到就盯着 DOM，元素一出现立刻取值（比死等满 5 秒快得多）
          let observer;
          const finish = setTimeout(() => {
            observer?.disconnect();
            resolve('');
          }, wait);
          observer = new MutationObserver(() => {
            if (pick()) {
              clearTimeout(finish);
              observer.disconnect();
            }
          });
          observer.observe(document.documentElement, {
            childList: true,
            subtree: true,
            characterData: true,
          });
        }),
    });
    text = (results?.[0]?.result || '').trim();
  } catch (err) {
    // 受限页面（chrome://、扩展页等）注入会被拒，属正常情况，不打扰用户
    console.warn('[sniffer] 读取页面标题失败', err);
    return;
  }
  if (!text) return;

  await withState((state) => {
    const entry = state[tabId];
    // 读取期间（可能等了几秒）用户可能已经跳走，认一下地址再写
    if (!entry || entry.url !== url) return;
    entry.pageTitle = text;
  });
}

// 途径 1：URL 后缀直判。用非阻塞模式（第三个参数不传 'blocking'），
// MV3 里 blocking 已被废弃，而观测本来也不需要拦。
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (details.tabId < 0) return;          // 不属于任何标签页（SW 自身、预加载等）
    if (details.type === 'main_frame') return; // 主文档由 tabs.onUpdated 负责
    if (M3U8_URL.test(details.url)) {
      recordHit(details.tabId, {
        url: details.url,
        kind: 'url',
        type: details.type,
        initiator: details.initiator || '',
        at: details.timeStamp || Date.now(),
      });
      return;
    }
    // 途径 3：封面图。先按扩展名廉价预筛，命中才去比对站点规则。
    if (IMAGE_EXT.test(details.url)) {
      recordCover(details.tabId, {
        url: details.url,
        type: details.type,
        at: details.timeStamp || Date.now(),
      });
    }
  },
  { urls: ['*://*/*'] }
);

// 途径 2：Content-Type 兜底。少数站点把播放列表挂在无后缀的路径上。
chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (details.tabId < 0) return;
    if (!details.responseHeaders) return;
    if (M3U8_URL.test(details.url)) return;  // 已经由途径 1 记过，不必重复

    const contentType = details.responseHeaders
      .filter((h) => h.name && h.name.toLowerCase() === 'content-type')
      .map((h) => h.value || '')
      .join(';');
    if (!HLS_MIME.test(contentType)) return;

    recordHit(details.tabId, {
      url: details.url,
      kind: 'mime',
      type: details.type,
      initiator: details.initiator || '',
      at: details.timeStamp || Date.now(),
    });
  },
  { urls: ['*://*/*'] },
  ['responseHeaders']
);
