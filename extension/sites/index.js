/**
 * 站点识别注册表
 *
 * 全部「嗅探哪些站点」的判断都收敛在这里，background 与 popup 共用同一份。
 *
 * 为什么单独抽一个目录：这两个入口原本各写了一份正则，结果
 * background 写 `/video/`、popup 写 `/videos/` —— 两边不一致的表现很难查：
 * 后台其实在正常抓数据，弹窗却一口咬定「当前页面不在监听范围」。
 * 现在改站点只动 `sites/` 下的文件，不可能再出现两边打架。
 *
 * 加站点：新建 `sites/<域名>.js` → 在下面 import → 加进 SITES 数组。
 */
import jableTv from './jable.tv.js';

/** 生效中的站点。`enabled: false` 的直接不参与匹配。 */
export const SITES = [jableTv].filter((site) => site && site.enabled !== false);

/** pattern → RegExp 缓存。匹配在每个请求上都会跑，不能每次重新编译。 */
const compiled = new Map();

function toRegExp(pattern) {
  const hit = compiled.get(pattern);
  if (hit) return hit;
  // 先把正则元字符转义，再把 `*` 放开成 `.*`
  const escaped = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  const re = new RegExp(`^${escaped}$`, 'i');
  compiled.set(pattern, re);
  return re;
}

/**
 * 判断一个地址属于哪个站点。
 *
 * @param {string} url 标签页地址（或任意 URL）
 * @returns {object|null} 命中的站点定义；都不命中返回 null
 */
export function matchSite(url) {
  if (typeof url !== 'string' || !url) return null;
  for (const site of SITES) {
    for (const pattern of site.pages || []) {
      if (toRegExp(pattern).test(url)) return site;
    }
  }
  return null;
}

/**
 * 判断一个请求地址是否是该站点的封面图。
 *
 * 封面模式写在站点文件的 `covers` 数组里，写法与 `pages` 完全一致（通配 + 整条锚定）。
 * 返回 boolean 而不是站点对象，因为调用方已经知道自己在哪个站点上。
 *
 * @param {string} url 请求地址
 * @param {object|null} site 已经匹配上的站点
 */
export function matchCover(url, site) {
  if (!site || typeof url !== 'string' || !url) return false;
  for (const pattern of site.covers || []) {
    if (toRegExp(pattern).test(url)) return true;
  }
  return false;
}

/** 只需要布尔值时用这个，读起来更直白。 */
export function isWatched(url) {
  return matchSite(url) !== null;
}
