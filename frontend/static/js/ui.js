/* ==========================================================================
   MediaManager —— UI 反馈组件（轻量，不依赖任何第三方库）
   - toast 轻提示
   - confirm / alert 对话框
   - loading 遮罩
   - 主题切换（dark / light，持久化到 localStorage）
   ========================================================================== */
(function (global) {
  'use strict';

  var MM = (global.MM = global.MM || {});
  var ui = {};

  /* ------------------------------------------------------------------ 主题 */
  function applyTheme(theme) {
    var html = document.documentElement;
    html.setAttribute('data-theme', theme);
    // 同步 Element Plus（html.dark）与 Vant（van-theme-dark）
    html.classList.toggle('dark', theme === 'dark');
    html.classList.toggle('van-theme-dark', theme === 'dark');
  }

  ui.getTheme = function () {
    var saved = null;
    try {
      saved = global.localStorage.getItem(MM.config.THEME_KEY);
    } catch (e) {
      saved = null;
    }
    if (saved) return saved;
    // 默认取系统偏好，无偏好时用暗色
    if (global.matchMedia && global.matchMedia('(prefers-color-scheme: light)').matches) {
      return 'light';
    }
    return 'dark';
  };

  ui.setTheme = function (theme) {
    applyTheme(theme);
    try {
      global.localStorage.setItem(MM.config.THEME_KEY, theme);
    } catch (e) {
      /* 忽略隐私模式写入失败 */
    }
  };

  ui.toggleTheme = function () {
    var next = ui.getTheme() === 'dark' ? 'light' : 'dark';
    ui.setTheme(next);
    // 通知页面（如图表重绘）
    global.dispatchEvent(new CustomEvent('mm:theme-change', { detail: { theme: next } }));
    return next;
  };

  /** 页面加载时立即应用，避免闪白 */
  ui.initTheme = function () {
    applyTheme(ui.getTheme());
  };

  /* ------------------------------------------------------------------ Toast */
  var toastHost = null;
  ui.toast = function (message, type, duration) {
    type = type || 'info';
    duration = duration || 2400;
    if (!toastHost) {
      toastHost = document.createElement('div');
      toastHost.className = 'mm-toasts';
      document.body.appendChild(toastHost);
    }
    var el = document.createElement('div');
    el.className = 'mm-toast mm-toast--' + type;
    el.textContent = message;
    toastHost.appendChild(el);
    setTimeout(function () {
      el.style.transition = 'opacity .25s, transform .25s';
      el.style.opacity = '0';
      el.style.transform = 'translateY(-8px)';
      setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      }, 260);
    }, duration);
    return el;
  };
  ui.success = function (msg) {
    return ui.toast(msg, 'success');
  };
  ui.error = function (msg) {
    return ui.toast(msg, 'error', 3200);
  };
  ui.warning = function (msg) {
    return ui.toast(msg, 'warning');
  };
  ui.info = function (msg) {
    return ui.toast(msg, 'info');
  };

  /* -------------------------------------------------------------- 对话框 */
  function dialog(options) {
    return new Promise(function (resolve) {
      var opts = options || {};
      var mask = document.createElement('div');
      mask.style.cssText =
        'position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,.55);' +
        'display:grid;place-items:center;padding:20px;backdrop-filter:blur(2px);';
      var box = document.createElement('div');
      box.style.cssText =
        'width:100%;max-width:400px;background:var(--panel);border:1px solid var(--border);' +
        'border-radius:14px;box-shadow:var(--shadow-lg);padding:20px 20px 16px;';
      box.innerHTML =
        '<div style="font-size:15.5px;font-weight:600;margin-bottom:8px">' +
        MM.util.escapeHtml(opts.title || '提示') +
        '</div>' +
        '<div style="font-size:13.5px;color:var(--text-2);line-height:1.7;white-space:pre-wrap">' +
        MM.util.escapeHtml(opts.message || '') +
        '</div>' +
        '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px"></div>';

      var footer = box.querySelector('div:last-child');
      var cancelBtn = null;
      if (opts.cancel !== false) {
        cancelBtn = document.createElement('button');
        cancelBtn.className = 'mm-btn';
        cancelBtn.textContent = opts.cancelText || '取消';
        footer.appendChild(cancelBtn);
      }
      var okBtn = document.createElement('button');
      okBtn.className = 'mm-btn ' + (opts.danger ? 'mm-btn--danger' : 'mm-btn--primary');
      okBtn.textContent = opts.okText || '确定';
      footer.appendChild(okBtn);

      function close(result) {
        if (mask.parentNode) mask.parentNode.removeChild(mask);
        document.removeEventListener('keydown', onKey);
        resolve(result);
      }
      function onKey(e) {
        if (e.key === 'Escape') close(false);
        if (e.key === 'Enter') close(true);
      }
      if (cancelBtn) cancelBtn.onclick = function () { close(false); };
      okBtn.onclick = function () { close(true); };
      mask.onclick = function (e) {
        if (e.target === mask) close(false);
      };
      document.addEventListener('keydown', onKey);

      mask.appendChild(box);
      document.body.appendChild(mask);
      okBtn.focus();
    });
  }

  ui.confirm = function (message, options) {
    return dialog(
      Object.assign({ title: '确认操作', message: message, okText: '确定' }, options || {})
    );
  };
  ui.alert = function (message, title) {
    return dialog({ title: title || '提示', message: message, cancel: false, okText: '知道了' });
  };

  /* --------------------------------------------------------------- Loading */
  var loadingCount = 0;
  var loadingEl = null;
  ui.loading = function (text) {
    loadingCount++;
    if (!loadingEl) {
      loadingEl = document.createElement('div');
      loadingEl.style.cssText =
        'position:fixed;inset:0;z-index:9997;display:grid;place-items:center;' +
        'background:rgba(0,0,0,.35);backdrop-filter:blur(1px)';
      loadingEl.innerHTML =
        '<div style="display:flex;align-items:center;gap:10px;padding:12px 18px;' +
        'background:var(--panel);border:1px solid var(--border);border-radius:10px;' +
        'box-shadow:var(--shadow);font-size:13px">' +
        '<span style="width:16px;height:16px;border:2px solid var(--border-strong);' +
        'border-top-color:var(--primary);border-radius:50%;display:inline-block;' +
        'animation:mm-spin .8s linear infinite"></span>' +
        '<span class="mm-loading-text">' + MM.util.escapeHtml(text || '处理中…') + '</span></div>';
      document.body.appendChild(loadingEl);
    } else {
      var t = loadingEl.querySelector('.mm-loading-text');
      if (t && text) t.textContent = text;
    }
    var closed = false;
    return function close() {
      if (closed) return;
      closed = true;
      loadingCount = Math.max(0, loadingCount - 1);
      if (loadingCount === 0 && loadingEl) {
        if (loadingEl.parentNode) loadingEl.parentNode.removeChild(loadingEl);
        loadingEl = null;
      }
    };
  };

  /* ------------------------------------------------------------ 剪贴板 */
  ui.copy = function (text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () {
        ui.success('已复制');
      });
    }
    var input = document.createElement('textarea');
    input.value = text;
    input.style.position = 'fixed';
    input.style.opacity = '0';
    document.body.appendChild(input);
    input.select();
    try {
      document.execCommand('copy');
      ui.success('已复制');
    } catch (e) {
      ui.error('复制失败');
    }
    document.body.removeChild(input);
    return Promise.resolve();
  };

  MM.ui = ui;

  /* -------------------------------------------------------- Vant 能力封装
     放在 ui.js（两端共用）而不是 layout-web.js：
     管理端页面不加载 layout-web.js，若定义在那里，管理端调用
     MM.vant.toast(...) 会抛 "Cannot read properties of undefined (reading 'toast')"，
     并且异常发生在 .then() 里会被后续 .catch() 捕获 → 表现为"操作成功却弹报错、
     且后续刷新逻辑被跳过"。
     用户端有 Vant 时走 Vant，管理端没有 Vant 时自动回退到自研 toast（common.css 已定义样式）。 */
  MM.vant = {
    /** 轻提示：优先用 Vant，缺失时回退到自研 toast */
    toast: function (message, type) {
      var v = global.vant;
      if (v && v.showToast) {
        v.showToast({ message: message, type: type || 'text', duration: 2000 });
      } else {
        ui.toast(message, type === 'fail' ? 'error' : type === 'success' ? 'success' : 'info');
      }
    },
    confirm: function (message, title) {
      var v = global.vant;
      if (v && v.showConfirmDialog) {
        return v.showConfirmDialog({ title: title || '提示', message: message });
      }
      return title ? ui.confirm(message, { title: title }) : ui.confirm(message);
    }
  };
})(window);
