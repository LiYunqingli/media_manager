/* ==========================================================================
   MediaManager —— 通用工具函数
   ========================================================================== */
(function (global) {
  'use strict';

  var MM = (global.MM = global.MM || {});
  var util = {};

  /* ---------------------------------------------------------------- 时间 */
  /** 秒 -> MM:SS / HH:MM:SS */
  util.formatDuration = function (seconds) {
    var total = Math.max(0, Math.floor(Number(seconds) || 0));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    var pad = function (n) {
      return n < 10 ? '0' + n : '' + n;
    };
    return h > 0 ? h + ':' + pad(m) + ':' + pad(s) : pad(m) + ':' + pad(s);
  };

  /** 秒 -> 1小时23分（用于统计展示） */
  util.formatDurationCn = function (seconds) {
    var total = Math.max(0, Math.floor(Number(seconds) || 0));
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    if (h > 0) return h + ' 小时 ' + m + ' 分';
    return m + ' 分钟';
  };

  /* ---------------------------------------------------------------- 容量 */
  util.formatSize = function (bytes) {
    var value = Number(bytes) || 0;
    if (value < 1024) return Math.round(value) + ' B';
    var units = ['KB', 'MB', 'GB', 'TB'];
    var i = -1;
    do {
      value /= 1024;
      i++;
    } while (value >= 1024 && i < units.length - 1);
    return value.toFixed(value >= 100 ? 0 : value >= 10 ? 1 : 2) + ' ' + units[i];
  };

  /** 速度：字节/秒 */
  util.formatSpeed = function (bytesPerSecond) {
    var v = Number(bytesPerSecond) || 0;
    if (v <= 0) return '—';
    return util.formatSize(v) + '/s';
  };

  /* ---------------------------------------------------------------- 日期 */
  util.formatDate = function (input, withTime) {
    if (!input) return '';
    var d;
    if (typeof input === 'string') {
      // 后端返回 "2026-09-26 11:00:00" 形式，Safari 不认空格分隔
      d = new Date(input.indexOf('T') >= 0 ? input : input.replace(' ', 'T'));
    } else {
      d = new Date(input);
    }
    if (isNaN(d.getTime())) return String(input);
    var pad = function (n) {
      return n < 10 ? '0' + n : '' + n;
    };
    var date = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    if (!withTime) return date;
    return date + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  };

  util.fromNow = function (input) {
    if (!input) return '';
    var d =
      typeof input === 'string'
        ? new Date(input.indexOf('T') >= 0 ? input : input.replace(' ', 'T'))
        : new Date(input);
    if (isNaN(d.getTime())) return '';
    var diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return '刚刚';
    if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
    if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
    if (diff < 86400 * 30) return Math.floor(diff / 86400) + ' 天前';
    return util.formatDate(input);
  };

  /* ---------------------------------------------------------------- 数字 */
  util.formatCount = function (num) {
    var n = Number(num) || 0;
    if (n < 10000) return String(n);
    if (n < 100000000) return (n / 10000).toFixed(n >= 100000 ? 0 : 1).replace(/\.0$/, '') + '万';
    return (n / 100000000).toFixed(1).replace(/\.0$/, '') + '亿';
  };

  util.padZero = function (n, len) {
    var s = String(n);
    while (s.length < (len || 2)) s = '0' + s;
    return s;
  };

  /* ---------------------------------------------------------- 函数控制 */
  util.debounce = function (fn, wait) {
    var timer = null;
    return function () {
      var ctx = this;
      var args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(ctx, args);
      }, wait || 200);
    };
  };

  util.throttle = function (fn, wait) {
    var last = 0;
    var timer = null;
    return function () {
      var ctx = this;
      var args = arguments;
      var now = Date.now();
      var remain = (wait || 200) - (now - last);
      if (remain <= 0) {
        last = now;
        fn.apply(ctx, args);
      } else if (!timer) {
        timer = setTimeout(function () {
          last = Date.now();
          timer = null;
          fn.apply(ctx, args);
        }, remain);
      }
    };
  };

  util.sleep = function (ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  };

  /* ---------------------------------------------------------------- 字符串 */
  util.escapeHtml = function (text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };

  util.filenameExt = function (name) {
    var idx = String(name || '').lastIndexOf('.');
    return idx >= 0 ? String(name).slice(idx).toLowerCase() : '';
  };

  util.ua = {
    isMobile: function () {
      return /Android|iPhone|iPad|iPod|Windows Phone|HarmonyOS|Mobile/i.test(
        navigator.userAgent || ''
      );
    },
    isTouch: function () {
      return 'ontouchstart' in window || (navigator.maxTouchPoints || 0) > 0;
    }
  };

  /* ---------------------------------------------------------------- URL */
  util.query = function (key, defaultValue) {
    var params = new URLSearchParams(global.location.search);
    var value = params.get(key);
    return value === null || value === '' ? (defaultValue === undefined ? '' : defaultValue) : value;
  };

  util.buildUrl = function (path, params) {
    var url = path;
    if (params) {
      var search = new URLSearchParams();
      Object.keys(params).forEach(function (k) {
        var v = params[k];
        if (v !== undefined && v !== null && v !== '') search.append(k, v);
      });
      var qs = search.toString();
      if (qs) url += (url.indexOf('?') >= 0 ? '&' : '?') + qs;
    }
    return url;
  };

  util.go = function (path, params) {
    global.location.href = util.buildUrl(path, params);
  };

  /* ---------------------------------------------------------- 无封面占位 */
  var PALETTES = [
    ['#1e3a8a', '#0f172a'],
    ['#164e63', '#0f172a'],
    ['#3730a3', '#1e1b4b'],
    ['#0f766e', '#0f172a'],
    ['#7c2d12', '#1c1917'],
    ['#4c1d95', '#1e1b4b'],
    ['#1e40af', '#111827'],
    ['#065f46', '#052e2b']
  ];
  util.coverGradient = function (seed) {
    var text = String(seed == null ? '' : seed);
    var hash = 0;
    for (var i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) >>> 0;
    var p = PALETTES[hash % PALETTES.length];
    return 'linear-gradient(135deg,' + p[0] + ',' + p[1] + ')';
  };

  /** 取标题前 2 个字符作为占位文字 */
  util.coverInitials = function (title) {
    var t = String(title || '视频').replace(/\s+/g, '');
    return util.escapeHtml(t.slice(0, 2));
  };

  MM.util = util;
})(window);
