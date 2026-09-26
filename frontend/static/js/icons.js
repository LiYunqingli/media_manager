/* ==========================================================================
   MediaManager —— 图标系统（内联 SVG）
   取代原先散落各处的 emoji，统一线宽、端点与视觉密度。

   用法：
     MM.icon('search')                    -> 返回 <svg> 字符串（可塞进 innerHTML）
     MM.icon('play', 20)                  -> 指定像素尺寸
     <mm-icon name="search" :size="16" /> -> Vue 组件（需先注册组件）
   ========================================================================== */
(function (global) {
  'use strict';

  var MM = (global.MM = global.MM || {});

  /* 线描图标：默认 stroke 绘制，随字体颜色着色 */
  var STROKE = {
    search: '<circle cx="11" cy="11" r="7"/><path d="M20.6 20.6 16.3 16.3"/>',
    sun: '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.6v2.5M12 18.9v2.5M2.6 12h2.5M18.9 12h2.5M6.1 6.1 4.4 4.4M19.6 19.6l-1.7-1.7M17.9 6.1l1.7-1.7M4.4 19.6l1.7-1.7"/>',
    moon: '<path d="M20.2 14.6A8.6 8.6 0 0 1 9.4 3.8a8.6 8.6 0 1 0 10.8 10.8Z"/>',

    'volume-high':
      '<path d="M4 9.6h3.1L11.3 6v12L7.1 14.4H4Z"/><path d="M15.6 8.7a4.6 4.6 0 0 1 0 6.6M18.3 6a8 8 0 0 1 0 12"/>',
    'volume-low':
      '<path d="M4 9.6h3.1L11.3 6v12L7.1 14.4H4Z"/><path d="M15.6 8.7a4.6 4.6 0 0 1 0 6.6"/>',
    'volume-mute':
      '<path d="M4 9.6h3.1L11.3 6v12L7.1 14.4H4Z"/><path d="m16 9.8 5 4.9M21 9.8l-5 4.9"/>',

    fullscreen: '<path d="M4 9.2V4.5h4.7M19.9 9.2V4.5h-4.7M4 14.8v4.7h4.7M19.9 14.8v4.7h-4.7"/>',
    'fullscreen-exit':
      '<path d="M9.2 4.5v4.7H4.5M14.8 4.5v4.7h4.7M9.2 19.5v-4.7H4.5M14.8 19.5v-4.7h4.7"/>',
    'page-fullscreen':
      '<rect x="3" y="4.6" width="18" height="12.6" rx="2"/><path d="M8.6 20.9h6.8M12 17.2v3.7"/>',

    rewind: '<path d="M11.6 6.4v11.2L4.4 12Z"/><path d="M19.6 6.4v11.2L12.4 12Z"/>',
    forward: '<path d="M12.4 6.4v11.2L19.6 12Z"/><path d="M4.4 6.4v11.2L11.6 12Z"/>',

    settings:
      '<circle cx="12" cy="12" r="3.1"/><path d="M12 2.9v2.2M12 18.9v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.9 12h2.2M18.9 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6"/>',
    film:
      '<rect x="3" y="4.6" width="18" height="14.8" rx="2.4"/><path d="M7.8 4.6v14.8M16.2 4.6v14.8M3 9.4h4.8M3 14.6h4.8M16.2 9.4H21M16.2 14.6H21"/>',
    folder:
      '<path d="M3.5 7.6a2 2 0 0 1 2-2h3.4l2 2.4h7.6a2 2 0 0 1 2 2v7.4a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z"/>',
    grid:
      '<rect x="4" y="4" width="7" height="7" rx="1.7"/><rect x="13" y="4" width="7" height="7" rx="1.7"/><rect x="4" y="13" width="7" height="7" rx="1.7"/><rect x="13" y="13" width="7" height="7" rx="1.7"/>',
    users:
      '<circle cx="9.2" cy="8.2" r="3.4"/><path d="M3.4 19.6a5.8 5.8 0 0 1 11.6 0M16.6 5.3a3.4 3.4 0 0 1 0 6.6M17.6 14.3a5.8 5.8 0 0 1 3 5.3"/>',
    user: '<circle cx="12" cy="8.2" r="3.6"/><path d="M5.2 20a6.8 6.8 0 0 1 13.6 0"/>',
    chart: '<path d="M4.6 19.4v-5M9.8 19.4V8.2M15 19.4v-8.6M20.2 19.4V4.6"/>',
    trend: '<path d="M3.6 16.6 9.2 11l3.5 3.5L20.4 7"/><path d="M15.8 7h4.6v4.6"/>',
    info: '<circle cx="12" cy="12" r="8.6"/><path d="M12 11.2v5.4M12 7.8h.01"/>',
    link:
      '<path d="M10.2 13.8a4 4 0 0 0 5.7 0l2.7-2.7a4 4 0 1 0-5.7-5.7l-1.3 1.3"/><path d="M13.8 10.2a4 4 0 0 0-5.7 0l-2.7 2.7a4 4 0 0 0 5.7 5.7l1.3-1.3"/>',
    clock: '<circle cx="12" cy="12" r="8.6"/><path d="M12 7.2V12l3.2 2.1"/>',
    calendar:
      '<rect x="3.6" y="5.2" width="16.8" height="15.2" rx="2.2"/><path d="M3.6 10h16.8M8.4 3.4v3.4M15.6 3.4v3.4"/>',
    hourglass:
      '<path d="M7 3.6h10M7 20.4h10M8.2 3.6v3.3c0 2 3.8 3.5 3.8 5.1s-3.8 3.1-3.8 5.1v3.3M15.8 3.6v3.3c0 2-3.8 3.5-3.8 5.1s3.8 3.1 3.8 5.1v3.3"/>',
    eye: '<path d="M2.6 12S6.1 5.6 12 5.6 21.4 12 21.4 12 17.9 18.4 12 18.4 2.6 12 2.6 12Z"/><circle cx="12" cy="12" r="3"/>',
    box: '<path d="m12 3 8.2 4.3v9.4L12 21l-8.2-4.3V7.3Z"/><path d="m4 7.3 8 4.3 8-4.3M12 11.6V21"/>',
    monitor: '<rect x="3" y="4.6" width="18" height="12.4" rx="2"/><path d="M8.6 20.9h6.8M12 17v3.9"/>',
    document:
      '<path d="M7 3.6h6.6L19 9v11.4a1.6 1.6 0 0 1-1.6 1.6H7a1.6 1.6 0 0 1-1.6-1.6V5.2A1.6 1.6 0 0 1 7 3.6Z"/><path d="M13.4 3.6V9H19M9.6 13.2h6M9.6 16.6h6"/>',
    alert: '<path d="M12 4.2 21 19.6H3Z"/><path d="M12 10v4.2M12 16.9h.01"/>',
    inbox:
      '<path d="M3.4 13.4 6 5.4h12l2.6 8v5a1.6 1.6 0 0 1-1.6 1.6H5a1.6 1.6 0 0 1-1.6-1.6Z"/><path d="M3.4 13.4h5.4l1 2.6h4.4l1-2.6h5.4"/>',
    check: '<path d="m5 12.6 4.6 4.6L19 7.4"/>',
    close: '<path d="M6.2 6.2 17.8 17.8M17.8 6.2 6.2 17.8"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    'chevron-right': '<path d="m9.6 5.4 6.6 6.6-6.6 6.6"/>',
    'chevron-left': '<path d="M14.4 5.4 7.8 12l6.6 6.6"/>',
    'chevron-down': '<path d="m5.4 9.6 6.6 6.6 6.6-6.6"/>',
    'arrow-up': '<path d="M12 19.4V4.6M6.2 10.4 12 4.6l5.8 5.8"/>',
    'arrow-down': '<path d="M12 4.6v14.8M6.2 13.6 12 19.4l5.8-5.8"/>',
    'external-link':
      '<path d="M14 4.6h5.4V10"/><path d="M19.4 4.6 11.2 12.8"/><path d="M18.4 14v4.4a1.6 1.6 0 0 1-1.6 1.6H6a1.6 1.6 0 0 1-1.6-1.6V7.6A1.6 1.6 0 0 1 6 6h4.4"/>',
    refresh: '<path d="M20.4 12a8.4 8.4 0 1 1-2.5-6"/><path d="M20.4 4.6V10h-5.4"/>',
    upload: '<path d="M12 19.6V5.4M6.4 11 12 5.4 17.6 11"/><path d="M4.6 20.4h14.8"/>',
    download: '<path d="M12 4.4v14.2M6.4 13 12 18.6 17.6 13"/><path d="M4.6 20.4h14.8"/>',
    image:
      '<rect x="3.4" y="5" width="17.2" height="14" rx="2"/><circle cx="9" cy="10.2" r="1.6"/><path d="m4.6 17.4 4.7-4.2 3.3 2.9 2.6-2.2 4.2 3.5"/>',
    trash:
      '<path d="M4.8 7.4h14.4M9.6 7.4V5.2h4.8v2.2"/><path d="m6.8 7.4.9 12a1.5 1.5 0 0 0 1.5 1.4h5.6a1.5 1.5 0 0 0 1.5-1.4l.9-12"/>',
    edit: '<path d="M16.4 4.6 19.4 7.6 9.2 17.8l-3.9.9.9-3.9Z"/>',
    fire:
      '<path d="M12 3.6c3 3.6 5.6 6.3 5.6 9.7a5.6 5.6 0 0 1-11.2 0c0-1.6.7-3 1.7-4.3.4 1.3 1.2 2 2.1 2 .5-2.7.7-5.1 1.8-7.4Z"/>',
    sparkle: '<path d="M12 3.6 13.8 9l5.4 1.9-5.4 1.9L12 18.2l-1.8-5.4L4.8 10.9 10.2 9Z"/>',
    compass: '<circle cx="12" cy="12" r="8.6"/><path d="m15.6 8.4-2 5.2-5.2 2 2-5.2Z"/>',
    bolt: '<path d="M13.2 3.4 5.6 13.2h5.2l-.8 7.4 7.6-9.8h-5.2Z"/>',
    book: '<path d="M12 6.6C10.4 5.3 8.4 4.6 4.6 4.6v12.8c3.8 0 5.8.7 7.4 2 1.6-1.3 3.6-2 7.4-2V4.6c-3.8 0-5.8.7-7.4 2Z"/><path d="M12 6.6v12.8"/>',
    'more-horizontal':
      '<circle cx="5.6" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="18.4" cy="12" r="1.5"/>',
    star: '<path d="m12 4 2.5 5.1 5.6.8-4.1 3.9 1 5.6L12 16.7 7 19.4l1-5.6L3.9 9.9l5.6-.8Z"/>'
  };

  /* 面性图标（实心，不描边） */
  var FILLED = {
    play: '<path d="M8.6 5.6a.9.9 0 0 1 1.36-.77l9.4 6.4a.9.9 0 0 1 0 1.54l-9.4 6.4A.9.9 0 0 1 8.6 18.4Z"/>',
    pause: '<rect x="7.2" y="5.6" width="3.6" height="12.8" rx="1.2"/><rect x="13.2" y="5.6" width="3.6" height="12.8" rx="1.2"/>',
    'star-filled': '<path d="m12 3.6 2.62 5.31 5.86.85-4.24 4.13 1 5.84L12 16.99l-5.24 2.75 1-5.84-4.24-4.13 5.86-.85Z"/>',
    'more-horizontal': '<circle cx="5.6" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="18.4" cy="12" r="1.7"/>'
  };

  /**
   * 生成图标 SVG 字符串。
   * @param {string} name  图标名
   * @param {number} [size] 像素尺寸，默认 1em（随字号缩放）
   * @returns {string} SVG 标记
   */
  MM.icon = function (name, size) {
    var filled = FILLED[name];
    var stroke = STROKE[name];
    if (!filled && !stroke) {
      // 未知图标给一个占位方块，避免页面出现空白与报错
      MM.log && MM.log('未知图标：' + name);
      stroke = '<rect x="5" y="5" width="14" height="14" rx="3"/>';
    }
    var dim = size ? 'width="' + size + '" height="' + size + '"' : 'width="1em" height="1em"';
    var open =
      '<svg class="mm-svg" ' + dim + ' viewBox="0 0 24 24" aria-hidden="true" focusable="false" ';
    if (filled) {
      return open + 'fill="currentColor" stroke="none">' + filled + '</svg>';
    }
    return (
      open +
      'fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
      stroke +
      '</svg>'
    );
  };

  MM.iconNames = Object.keys(STROKE).concat(
    Object.keys(FILLED).filter(function (k) {
      return !STROKE[k];
    })
  );

  /* --------------------------------------------------- Vue 组件：<mm-icon> */
  MM.components = MM.components || {};
  MM.components['mm-icon'] = {
    name: 'MmIcon',
    props: {
      name: { type: String, required: true },
      size: { type: [Number, String], default: 0 },
      label: { type: String, default: '' }
    },
    computed: {
      markup: function () {
        return MM.icon(this.name, this.size ? Number(this.size) : 0);
      }
    },
    template:
      '<span class="mm-icon" :class="{ \'mm-icon--block\': !size }" ' +
      ':aria-label="label || null" :role="label ? \'img\' : null" v-html="markup"></span>'
  };
})(window);
