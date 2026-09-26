/**
 * 生成给 MediaManager 管理端「一键粘贴」用的任务文本。
 *
 * 单独成文件、不塞在 `popup.js` 里：这是**纯函数**，不碰 DOM，能脱离浏览器
 * 直接跑测试。而它和管理端 `parseTaskText` 是一对写死的约定 —— 两侧格式必须
 * 一字不差地对上，正是最该被测住的地方。
 *
 * 格式：
 *   # MediaManager 下载任务
 *   url=https://example.com/hls/index.m3u8
 *   title=视频名称
 *   cover=https://example.com/poster.jpg
 *
 * 约定：
 *   · `#` 开头是注释行，解析方忽略；
 *   · 一行一个键值对；值为空就**不输出这一行**，免得把管理端已填的内容覆盖成空；
 *   · 值里的换行压成空格，否则会破坏「一行一条」的结构；
 *   · 键名固定 `url` / `title` / `cover`。
 */

/** 拼一行 `key=value`；值为空返回空串，好让调用方直接 filter 掉。 */
function kvLine(key, value) {
  const text = String(value ?? '')
    .trim()
    .replace(/\s*\r?\n\s*/g, ' ');
  return text ? `${key}=${text}` : '';
}

/**
 * @param {object} entry background 写在 storage.session 里的标签页条目
 * @returns {string} 多行文本，可直接复制粘贴给管理端
 */
export function buildTaskText(entry) {
  return [
    '# MediaManager 下载任务',
    kvLine('url', entry?.hits?.[0]?.url),
    kvLine('title', entry?.pageTitle),
    kvLine('cover', entry?.covers?.[0]?.url),
  ]
    .filter(Boolean)
    .join('\n');
}
