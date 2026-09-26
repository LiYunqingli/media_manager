/* ==========================================================================
   MediaManager —— 全局配置
   所有前端可调参数集中在此文件，页面通过 window.MM.config 读取。
   ========================================================================== */
(function (global) {
  'use strict';

  var IS_HTTPS = global.location && global.location.protocol === 'https:';
  var HOST = global.location ? global.location.host : '127.0.0.1:8000';

  var config = {
    /** 后端接口前缀 */
    API_BASE: '/api',
    /** 媒体文件前缀（视频/封面） */
    MEDIA_BASE: '/media',
    /** WebSocket 前缀（上传进度推送） */
    WS_BASE: (IS_HTTPS ? 'wss://' : 'ws://') + HOST,

    /** localStorage 键名 */
    TOKEN_KEY: 'mm_token',
    USER_KEY: 'mm_user',
    THEME_KEY: 'mm_theme',

    /** 页面路径（前后端分离，集中一处便于改目录） */
    PATHS: {
      webLogin: '/login.html',
      webHome: '/index.html',
      webCategory: '/category.html',
      webDetail: '/detail.html',
      webPlay: '/play.html',
      webSearch: '/search.html',
      webFavorites: '/favorites.html',
      webHistory: '/history.html',
      webProfile: '/profile.html',
      adminLogin: '/admin/login.html',
      adminHome: '/admin/index.html'
    },

    /** 请求超时（毫秒） */
    REQUEST_TIMEOUT: 20000,
    /** 上传相关默认值（实际以服务端 /upload/init 返回为准） */
    UPLOAD: {
      /** 上传文件的并发数 */
      CONCURRENCY: 3,
      /** 单个分片失败重试次数 */
      RETRY: 3,
      /** 重试退避基数（毫秒） */
      RETRY_BASE: 800,
      /** 分片单个请求超时 */
      TIMEOUT: 120000
    },
    /** 播放器默认参数 */
    PLAYER: {
      /** 长按触发倍速的时长（毫秒） */
      LONG_PRESS_DELAY: 450,
      /** 长按时的倍速 */
      LONG_PRESS_RATE: 3,
      /** 可选倍速 */
      RATES: [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0],
      /** 亮度/音量每次手势满屏变化量 */
      GESTURE_RANGE: 100,
      /** 快进/快退基础秒数 */
      SEEK_STEP: 10,
      /** 控制栏自动隐藏延时（毫秒） */
      HIDE_DELAY: 3000,
      /**
       * 播放器高度上限（视口百分比）。
       * 容器会按视频真实宽高比伸缩（竖屏视频不再被挤成窄竖条），
       * 超过该上限时反向收紧宽度，从而在「宽高都受限」时仍保持比例不失真。
       */
      MAX_HEIGHT_VH: 76
    },
    /** 观看进度上报 */
    PLAY_REPORT: {
      /** 心跳间隔（秒），与后端 business.heartbeat_interval_seconds 保持一致 */
      INTERVAL: 5,
      /** 续播：进度超过该比例则从头播放 */
      RESUME_TO_END: 95,
      /** 小于该秒数不提示续播 */
      RESUME_MIN: 5
    },
    /** 分页默认每页条数 */
    PAGE_SIZE: 20,
    /** 调试日志 */
    DEBUG: false
  };

  global.MM = global.MM || {};
  global.MM.config = config;

  global.MM.log = function () {
    if (config.DEBUG) {
      console.log.apply(console, ['[MM]'].concat(Array.prototype.slice.call(arguments)));
    }
  };
})(window);
