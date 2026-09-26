# m3u8 嗅探器（Chrome 扩展）

挂在浏览器上的采集端：把你正在看的视频页里**实际发出的 m3u8 请求地址**、
**封面图地址**和**视频标题**抓出来展示，方便复制去 MediaManager 的
「m3u8 下载导入」建任务（见 [doc/11](../doc/11-m3u8下载导入.md)）。

当前版本做**捕获 + 展示 + 一键复制**，还没有直接投递到后端的按钮 ——
投递走「插件一键复制 → 管理端一键粘贴」，见下。

## 安装

1. 地址栏打开 `chrome://extensions`
2. 右上角打开 **开发者模式**
3. 点 **加载已解压的扩展程序**，选这个 `extension/` 目录
4. 扩展栏出现一个深色播放三角图标，点它打开弹窗

Edge 同理（`edge://extensions`），内核一致。

## 用法

1. 打开目标视频页
2. **刷新一次页面**（扩展只在页面导航之后才开始监听，装完不刷新抓不到任何东西）
3. 页面加载过程中播放器会去拉播放列表，此时点扩展图标，列表里就是抓到的地址
4. 单条点「复制」拿到那一条纯链接；点底部「一键复制」拿到**键值对文本**（见下）
5. 最上方**标题**行是站点规则从页面 DOM 里读的视频标题，也可单独复制
6. **封面图**区显示抓到的封面地址和缩略图

翻页、换视频会**自动清空**上一轮的捕获；点「清空」可手工清掉当前标签页的 m3u8 列表
（标题与封面不受影响 —— 这两项抓一次就稳定，要清掉刷新页面即可）。

> 标题不是拿浏览器标签标题凑的，而是按站点规则从页面里 **querySelector 读出来的**，
> 所以不会带上「- Jable TV」这类站点后缀。
>
> 封面是靠**观测图片请求**拿到的，所以它得真的被浏览器请求过：页面上的缩略图若是
> `loading="lazy"` 且没滚到视野里，或者被缓存短路，就可能抓不到。没抓到就滚一下页面
> 或刷新一次。

### 「一键复制」输出什么

一段键值对文本，直接粘到管理端就能把链接、名称、封面一次填好：

```
# MediaManager 下载任务
url=https://cdn.example.com/hls/index.m3u8?token=abc
title=T38-071 中文字幕
cover=https://assets.example.com/videos/t38-071/preview.jpg
```

- `#` 开头是注释行，管理端会忽略；
- 值为空的那一行**不输出** —— 免得把管理端已经填好的内容覆盖成空；
- 值里的换行会压成空格，保证「一行一条」的结构不被破坏；
- `url` 只取**列表第一条**（最新捕获的那条）。一个下载任务只吃一个地址，
  想换另一条就用列表里的单条「复制」。

粘贴到 `frontend/admin/upload.html` 的 m3u8 表单：点「一键粘贴」，或者直接把这段内容
粘进链接输入框（会自动识别拆分）。生成逻辑在 `task-text.js`，解析在管理端页面里，
**两侧是一对写死的约定，改格式必须两边一起改**。

## 工作原理

`background.js` 里四条捕获途径：

| 途径 | 判定依据 | 覆盖情况 |
| --- | --- | --- |
| `onBeforeRequest` | URL 以 `.m3u8` 结尾（允许带 `?` / `#`） | 绝大多数站点 |
| `onHeadersReceived` | 响应 `Content-Type` 是 HLS 的 MIME | URL 不带后缀的变体 |
| `onBeforeRequest` | 图片扩展名 **且** 命中站点的 `covers` 模式 | 封面图 |
| `tabs.onUpdated` | `status=complete` 后注入脚本，按站点 `selectors` 读 DOM | 视频标题 |

四条都不改动请求/页面内容，只观测。

封面走的是**两层判定**：先按 `.jpg/.jpeg/.png/.webp/.avif` 扩展名做一次廉价预筛，
命中之后才去读存储比对站点规则。页面上的 js / css / 接口请求远多于图片，
这一层让绝大多数请求在**不碰 `storage.session`** 的情况下直接短路掉 —— 而只靠扩展名
是不够的，站点的 logo、其它缩略图都是图片，必须再对上 `covers` 模式才算。

### 标题为什么是「注入脚本」而不是 content script

service worker 摸不到 DOM，读标题只能注脚本。这里用的是
`chrome.scripting.executeScript({ func, args })` 内联注入，**没有单独的 content script 文件**：

- content script **不支持 ESM**，没法 `import` 站点规则 —— 那样选择器就得在
  `sites/` 和 content script 两处维护，正是之前 `background.js` / `popup.js`
  各写一份正则那个坑的重演；
- 内联注入可以把站点规则里的选择器当 `args` 传进去，规则仍然只有 `sites/` 一份；
- 只有**配了 `selectors` 的站点**才会注入，其余站点一个脚本都不跑。

注入的 `func` 会先立即 `querySelector` 一次，读不到就挂 `MutationObserver` 盯 DOM
（最多 5 秒）—— 前端渲染的站点在 `complete` 时元素往往还没长出来，死等固定延迟要么慢
要么漏。读回来的结果写入前会再核对一次地址，避免用户在这几秒里跳走了还被写脏。

**只在配置过的站点上工作**：每次记录前都用 `sites/index.js` 的 `matchSite()`
核对这个标签页的地址。当前配的是 `https://jable.tv/videos/*`（`www.` 前缀也认），
见 [站点识别](#站点识别sites)。命中不了就直接丢弃 ——
即便它恰好在别的站点抓到了 `.m3u8`，也不会写进本地存储。

状态全部放 `chrome.storage.session`：

- 不放模块级变量，因为 MV3 的 service worker 会被随时回收，内存变量的表现是
  「过一会儿抓到的链接全没了」；
- 不放 `storage.local`，因为那是持久化的，关掉浏览器还在，没必要留这个痕；
- 读写用一条 Promise 链串行化。master 与 media 两条播放列表请求常常同一毫秒到达，
  并发写会互相覆盖，表现为「只抓到一条」。

## 权限说明

| 权限 | 用途 |
| --- | --- |
| `webRequest` | 观测请求（不带 `blocking`，只读） |
| `storage` | `storage.session` 存捕获结果 |
| `tabs` | 拿标签页当前 URL，用于判定「是不是目标页面」 |
| `scripting` | 往页面注入内联脚本，读标题等 DOM 信息（仅在站点配了 `selectors` 时） |
| `host_permissions: *://*/*` | 见下 |

`*://*/*` 看着吓人，但要抓 m3u8 就必须给：**播放列表的域名通常是第三方 CDN，
和页面域名不是一回事**，事先没法枚举。真正的收口在 `sites/` 目录 ——
不命中站点规则的页面一律不记录。

如果哪天确认了 CDN 域名固定，可以把 `host_permissions` 收窄成
`["*://*.jable.tv/*", "*://cdn.example.com/*"]`，再用 `chrome.webRequest` 的
`urls` 过滤器同步改窄 —— 这样安装时的警告会少很多。

## 站点识别（`sites/`）

**嗅探哪些站点，全部是这个目录说了算**，后台和弹窗共用同一份判定，加站点不用改逻辑代码。

```
sites/
├─ index.js        注册表：import 各站点 + 导出 matchSite() / matchCover()
└─ jable.tv.js     一个站点一个文件
```

一个站点文件里有三部分配置：

| 字段 | 写法 | 作用 |
| --- | --- | --- |
| `pages` | 通配模式数组（`*` 匹配任意字符，**整条锚定**） | 页面地址白名单，命中后该标签页开始被记录 |
| `covers` | 同上 | 封面图地址模式，命中后进弹窗的封面区 |
| `selectors` | CSS 选择器（取**第一个**匹配元素） | 从页面 DOM 里读的信息，目前支持 `title` |

当前 jable.tv 的规则（`sites/jable.tv.js`）：

```js
pages: [
  'https://jable.tv/videos/*',        // 详情页：https://jable.tv/videos/t38-071/
  'https://www.jable.tv/videos/*',
  'https://jable.tv/video/*',         // 单数，站点未使用，留作改版兜底
  'https://www.jable.tv/video/*',
],
covers: [
  '*preview.jpg*',                    // 封面常常挂在第三方 CDN 上，所以不写死域名
],
selectors: {
  title: '.header-left h4',           // 视频标题；多个匹配时取第一个
},
```

> **注意 `pages` 是复数 `videos`** —— 详情页与列表页都是这个前缀。
> 写成单数 `video` 会表现为「后台没抓到 / 弹窗显示不在监听范围」。

> `covers` **故意不写域名**：封面图常在 CDN 上，域名与页面域名无关，
> 写死域名站点换 CDN 就失效了，所以只认文件名特征。
> 代价是 `https://x.com/xxxpreview.jpgfoo` 这种也会命中 —— 实际站点上遇不到。

> `selectors` **没配就不注入脚本** —— 不想让扩展碰页面 DOM 的站点把它删掉即可，
> 那样就退化成纯 webRequest 观测。

### 加一个新站点

1. 复制 `sites/jable.tv.js` 成 `sites/<域名>.js`，改 `id` / `name` / `pages` / `covers` / `selectors`：

```js
export default {
  id: 'example.com',
  name: '示例站',
  enabled: true,
  pages: ['https://example.com/watch/*'],   // `*` 匹配任意字符
  covers: ['*cover.jpg*'],                  // 不需要封面就把这行删掉
  selectors: { title: 'h1.video-title' },   // 不读 DOM 就把这段删掉
};
```

2. 在 `sites/index.js` 顶部 import 一行，并加进 `SITES` 数组：

```js
import exampleCom from './example.com.js';
export const SITES = [jableTv, exampleCom].filter(...);
```

3. 回 `chrome://extensions` 点一下该扩展的**刷新**按钮。

### 停用一个站点

把该文件的 `enabled` 改成 `false`（文件留着，方便随时开回来），
或者直接从 `SITES` 数组里移除。

> 页面地址**必须**整条匹配（正则两头都锚了 `^…$`）。所以
> `https://jable.tv/videos/*` 不会误命中 `https://jable.tv.evil.com/videos/x` 这种
> 同前缀的钓鱼域名，`http://` 也不在范围内。

## 目录结构

```
extension/
├─ manifest.json      MV3 清单（service worker 以 ES module 方式加载）
├─ background.js      service worker：监听 + 记录 + 注入读标题
├─ sites/             站点识别规则：index.js 注册表 + 一个站点一个文件
├─ task-text.js       生成「一键复制」的键值对文本（纯函数，无 DOM 依赖）
├─ popup.html/css/js  弹窗：展示 + 复制
└─ icons/             16 / 32 / 48 / 128
```

> `background.js` 与 `popup.js` 都通过 `import ... from './sites/index.js'` 取判定，
> 因此 manifest 里的 service worker 声明带了 `"type": "module"`，
> `popup.html` 的脚本标签也必须是 `type="module"`。
>
> 没有 content script —— 读 DOM 靠的是 `chrome.scripting.executeScript` 内联注入，
> 原因见 [标题为什么是「注入脚本」](#标题为什么是注入脚本而不是-content-script)。

## 已知限制

- **必须刷新页面**才会开始监听。装完扩展后当前这个已经加载完的页面抓不到东西，
  这是 MV3 的固有行为，不是 bug。
- 只认 `https://`，`http://jable.tv/...` 不在范围内。
- 捕获的是**页面实际发出的**请求。如果播放器因为某种原因根本没请求播放列表
  （比如被广告拦截插件挡了），这里自然是空的 —— 顺手也能当排查手段用。
- **封面同理**：`loading="lazy"` 且没滚到视野里、或者浏览器直接用缓存短路，
  都可能抓不到。滚动一下页面或刷新即可。封面区只取第一条，其余条数会在下面标注。
- **标题**是 `complete` 之后读的，若站点把标题渲染得特别晚（超过 5 秒），会读到空。
  这时刷新一次即可。选择器写错了同样是静默读不到 —— 判断依据就是弹窗里标题行不出现。
- 每标签页最多留 60 条 m3u8、10 条封面，防止长会话把 session 存储撑爆
  （multi-bitrate 的 master 列表会产生多条，但不会到 60）。

## 下一步

现在是「一键复制 → 管理端一键粘贴」两步。真正的自动化是插件直接调后端投递：
后端已经有免登录的 `X-API-Token` 通道，`POST /api/admin/download/m3u8`，
入参 `{ url, title, cover_url, category_id }`。
弹窗里加一排「投递到 MediaManager」按钮 + 一个设置页存服务地址和令牌即可 ——
`task-text.js` 已经把这几个字段凑齐了，直接复用。
