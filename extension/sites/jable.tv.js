/**
 * 站点识别规则 · jable.tv
 *
 * ── 怎么加站点 ────────────────────────────────────────────────────────────
 * 1. 复制本文件为 `sites/<域名>.js`，改 id / name / pages；
 * 2. 到 `sites/index.js` 里 import 一行、加进 SITES 数组。
 *
 * ── 怎么停用 ──────────────────────────────────────────────────────────────
 * 把 `enabled` 改成 false（保留文件，方便随时开回来），
 * 或者直接从 index.js 的 SITES 里移除。
 */
export default {
  id: 'jable.tv',
  name: 'Jable',
  enabled: true,

  /**
   * 页面地址白名单，`*` 匹配任意字符（含 `/`）。
   *
   * 只有命中这里的地址，后台才会开始记录该标签页的请求；不命中的一律丢弃，
   * 连一个字节都不写进本地存储。
   *
   * 站点哪天改版换了路径，在这里加一行就行 —— 不用碰任何 JS 逻辑。
   */
  pages: [
    // 详情页真实路径是复数：https://jable.tv/videos/t38-071/
    'https://jable.tv/videos/*',
    'https://www.jable.tv/videos/*',
    // 单数只是历史猜测，站点并未使用；留着以免哪天改版回切。
    'https://jable.tv/video/*',
    'https://www.jable.tv/video/*',
  ],

  /**
   * 封面图地址模式，写法与 `pages` 一致（`*` 匹配任意字符，整条锚定）。
   *
   * 封面往往挂在第三方 CDN 上，**域名和页面域名不是一回事**，所以模式不写死域名，
   * 只认文件名特征。
   */
  covers: [
    '*preview.jpg*',
  ],

  /**
   * 页面信息提取：值一律是 CSS 选择器，取**第一个**匹配到的元素。
   *
   * 这几项要在页面加载完成后由 background 注入脚本去读（service worker 摸不到 DOM），
   * 所以只有声明了选择器的站点才会触发注入 —— 没配的站点连脚本都不会跑。
   */
  selectors: {
    /** 视频标题。jable 的详情页标题在 `.header-left` 里的第一个 h4。 */
    title: '.header-left h4',
  },
};
