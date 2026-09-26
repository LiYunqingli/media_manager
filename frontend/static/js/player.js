/* ==========================================================================
   MediaManager —— 自定义视频播放器
   一个 div 容器即可初始化，内部自建 DOM 与事件（不依赖任何框架）。

   功能清单
   --------
   [基础]  播放/暂停、进度条拖动与预览、缓冲进度、音量、静音、全屏、网页全屏、
           倍速菜单、时间显示、加载态、封面
   [手势]  长按倍速（松开恢复正常，默认 3x / 450ms 触发）
           水平滑动 = 拖动进度（跟手预览目标时间）
           左半边上下滑动 = 亮度（黑色遮罩模拟）
           右半边上下滑动 = 音量
           单击 = 显示 / 隐藏控制栏；双击 = 播放 / 暂停（PC 与移动端一致）
   [显隐]  控制栏默认隐藏；点击画面显示，再点隐藏；播放中 3 秒无操作自动隐藏，
           暂停 / 播放结束 / 全屏切换时保持显示。
   [键盘]  空格/K 播放暂停、←→ 快退快进、↑↓ 音量、M 静音、F 全屏、W 网页全屏、
           [ ] 调速、0-9 按百分比跳转
   [业务]  续播（记住上次位置）、观看进度自动上报（心跳，用于播放次数统计）
   ========================================================================== */
(function (global) {
  'use strict';

  var MM = (global.MM = global.MM || {});
  var util = MM.util;
  var PCFG = MM.config.PLAYER;

  function el(tag, className, html) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (html !== undefined) node.innerHTML = html;
    return node;
  }

  function Player(container, options) {
    this.container = typeof container === 'string' ? document.querySelector(container) : container;
    if (!this.container) throw new Error('播放器容器不存在');
    this.options = options || {};
    this.isTouch = util.ua.isTouch();

    this._built = false;
    this._controlsTimer = null;
    this._reportTimer = null;
    this._watchAccum = 0;
    this._delta = 0;
    this._lastReportAt = 0;
    this._dragging = false;
    this._brightness = 1;
    this._rate = 1;
    this._longPressTimer = null;
    this._longPressing = false;
    this._gesture = null;
    this._lastTapAt = 0;
    this._lastClickAt = 0;
    this._clickTimer = null;
    this._webFullscreen = false;
    this._destroyed = false;

    this._build();
    this._bindVideo();
    this._bindControls();
    this._bindGesture();
    this._bindKeyboard();
    this._bindWindow();
  }

  /* ==================================================================== 构建 */
  Player.prototype._build = function () {
    var self = this;
    var opts = this.options;
    this.container.classList.add('mp');
    if (!this.container.style.position) this.container.style.position = 'relative';

    this.container.innerHTML =
      '<video playsinline webkit-playsinline x5-playsinline preload="metadata"' +
      (opts.poster ? ' poster="' + util.escapeHtml(opts.poster) + '"' : '') +
      '></video>' +
      '<div class="mp__dim"></div>' +
      '<button class="mp__big-play" type="button" aria-label="播放" title="播放">' +
      MM.icon('play', 26) +
      '</button>' +
      '<div class="mp__loading mm-hide"></div>' +
      '<div class="mp__speed-badge">' + PCFG.LONG_PRESS_RATE.toFixed(1) + 'x 快进中</div>' +
      '<div class="mp__center-hint"></div>' +
      '<div class="mp__hint-tip" style="display:none"></div>' +
      '<div class="mp__gesture"></div>' +
      '<div class="mp__controls">' +
      '  <div class="mp__progress">' +
      '    <div class="mp__progress-track">' +
      '      <div class="mp__progress-loaded"></div>' +
      '      <div class="mp__progress-played"></div>' +
      '    </div>' +
      '    <div class="mp__progress-thumb"></div>' +
      '    <div class="mp__preview">00:00</div>' +
      '  </div>' +
      '  <div class="mp__bar">' +
      '    <button class="mp__icon-btn" data-act="play" type="button" title="播放 / 暂停">' +
      MM.icon('play', 18) +
      '</button>' +
      '    <span class="mp__time mm-current">00:00</span>' +
      '    <span class="mp__time mp__time-sep">/</span>' +
      '    <span class="mp__time mm-duration">00:00</span>' +
      '    <span class="mp__spacer"></span>' +
      '    <span class="mp__bar-tip">长按倍速 · 左右滑动调进度 · 左半屏亮度 / 右半屏音量</span>' +
      '    <div class="mp__rate">' +
      '      <button class="mp__icon-btn" data-act="rate" type="button" title="播放速度">1.0x</button>' +
      '    </div>' +
      '    <div class="mp__volume">' +
      '      <button class="mp__icon-btn" data-act="mute" type="button" title="静音">' +
      MM.icon('volume-high', 18) +
      '</button>' +
      '      <div class="mp__volume-slider">' +
      '        <input type="range" min="0" max="100" value="100" aria-label="音量" />' +
      '      </div>' +
      '    </div>' +
      '    <button class="mp__icon-btn" data-act="webfull" type="button" title="网页全屏">' +
      MM.icon('page-fullscreen', 17) +
      '</button>' +
      '    <button class="mp__icon-btn" data-act="fullscreen" type="button" title="全屏">' +
      MM.icon('fullscreen', 17) +
      '</button>' +
      '  </div>' +
      '</div>';

    this.video = this.container.querySelector('video');
    this.dim = this.container.querySelector('.mp__dim');
    this.bigPlay = this.container.querySelector('.mp__big-play');
    this.loading = this.container.querySelector('.mp__loading');
    this.centerHint = this.container.querySelector('.mp__center-hint');
    this.speedBadge = this.container.querySelector('.mp__speed-badge');
    this.hintTip = this.container.querySelector('.mp__hint-tip');
    this.gestureLayer = this.container.querySelector('.mp__gesture');
    this.controls = this.container.querySelector('.mp__controls');
    this.progress = this.container.querySelector('.mp__progress');
    this.track = this.container.querySelector('.mp__progress-track');
    this.loadedBar = this.container.querySelector('.mp__progress-loaded');
    this.playedBar = this.container.querySelector('.mp__progress-played');
    this.thumb = this.container.querySelector('.mp__progress-thumb');
    this.preview = this.container.querySelector('.mp__preview');
    this.timeCurrent = this.container.querySelector('.mm-current');
    this.timeDuration = this.container.querySelector('.mm-duration');
    this.btnPlay = this.container.querySelector('[data-act="play"]');
    this.btnMute = this.container.querySelector('[data-act="mute"]');
    this.btnRate = this.container.querySelector('[data-act="rate"]');
    this.btnFullscreen = this.container.querySelector('[data-act="fullscreen"]');
    this.btnWebfull = this.container.querySelector('[data-act="webfull"]');
    this.volumeInput = this.container.querySelector('.mp__volume input');
    this.inlineTip = this.container.querySelector('.mp__bar-tip');

    if (this.options.src) this.video.src = this.options.src;
    if (this.options.title) this.video.setAttribute('title', this.options.title);

    // 移动端隐藏冗长的键盘/手势说明
    if (this.isTouch) this.inlineTip.style.display = 'none';

    this._built = true;
    MM.log('播放器已初始化');
  };

  /* ================================================================== 视频事件 */
  Player.prototype._bindVideo = function () {
    var self = this;
    var v = this.video;

    v.addEventListener('loadedmetadata', function () {
      self.timeDuration.textContent = util.formatDuration(v.duration);
      self.bigPlay.style.display = 'none';

      // 续播
      var last = Number(self.options.lastPosition || 0);
      if (last > MM.config.PLAY_REPORT.RESUME_MIN && v.duration > 0) {
        var pct = (last / v.duration) * 100;
        if (pct < MM.config.PLAY_REPORT.RESUME_TO_END) {
          try {
            v.currentTime = last;
          } catch (e) {
            /* 某些浏览器元数据未就绪时会抛错，忽略 */
          }
          self.showCenterHint('已从 <b>' + util.formatDuration(last) + '</b> 继续播放', 2200);
        }
      }
      self._updateProgress();
      if (self.options.onReady) self.options.onReady(self);
      // 自动播放（桌面端浏览器可能拦截，属正常现象）
      if (self.options.autoplay) self.play();
    });

    v.addEventListener('play', function () {
      self.btnPlay.innerHTML = MM.icon('pause', 18);
      self.bigPlay.style.display = 'none';
      self._startReportTimer();
      self._autoHideControls();
      if (self.options.onPlay) self.options.onPlay();
    });
    v.addEventListener('pause', function () {
      self.btnPlay.innerHTML = MM.icon('play', 18);
      self.bigPlay.style.display = '';
      self._stopReportTimer();
      self._report(true);
      self._showControls(true);
      if (self.options.onPause) self.options.onPause();
    });
    v.addEventListener('waiting', function () {
      self.loading.classList.remove('mm-hide');
    });
    v.addEventListener('canplay', function () {
      self.loading.classList.add('mm-hide');
    });
    v.addEventListener('playing', function () {
      self.loading.classList.add('mm-hide');
    });
    v.addEventListener('timeupdate', function () {
      if (!self._dragging) self._updateProgress();
      self.timeCurrent.textContent = util.formatDuration(v.currentTime);
    });
    v.addEventListener('progress', function () {
      self._updateLoaded();
    });
    v.addEventListener('volumechange', function () {
      self.volumeInput.value = String(Math.round(v.volume * 100));
      self.btnMute.innerHTML = MM.icon(
        v.muted || v.volume === 0 ? 'volume-mute' : v.volume < 0.5 ? 'volume-low' : 'volume-high',
        18
      );
    });
    v.addEventListener('ratechange', function () {
      self.btnRate.textContent = v.playbackRate.toFixed(1) + 'x';
    });
    v.addEventListener('ended', function () {
      self._stopReportTimer();
      self._report(true);
      self.bigPlay.style.display = '';
      self._showControls(true);
      if (self.options.onEnded) self.options.onEnded();
    });
    v.addEventListener('error', function () {
      self.loading.classList.add('mm-hide');
      var err = v.error;
      var msg = '视频加载失败';
      if (err) {
        msg += '（' + ({ 1: '加载被中断', 2: '网络错误', 3: '解码失败', 4: '格式不支持' }[err.code] || '未知') + '）';
      }
      MM.ui.toast(msg, 'error', 4000);
      if (self.options.onError) self.options.onError(err);
    });

    // 屏蔽移动端长按弹出的原生菜单
    v.addEventListener('contextmenu', function (e) {
      e.preventDefault();
    });
  };

  /* ================================================================== 控件事件 */
  Player.prototype._bindControls = function () {
    var self = this;
    var v = this.video;

    this.container.querySelector('[data-act="play"]').addEventListener('click', function (e) {
      e.stopPropagation();
      self.togglePlay();
    });
    // 大播放键（封面态）直接起播
    this.bigPlay.addEventListener('click', function (e) {
      e.stopPropagation();
      self.play();
    });
    this.container.querySelector('[data-act="mute"]').addEventListener('click', function (e) {
      e.stopPropagation();
      v.muted = !v.muted;
      if (!v.muted && v.volume === 0) v.volume = 0.6;
      self._hint(
        v.muted ? 'volume-mute' : v.volume < 0.5 ? 'volume-low' : 'volume-high',
        v.muted ? '已静音' : '音量 ' + Math.round(v.volume * 100) + '%',
        900
      );
    });
    this.container.querySelector('[data-act="fullscreen"]').addEventListener('click', function (e) {
      e.stopPropagation();
      self.toggleFullscreen();
    });
    this.container.querySelector('[data-act="webfull"]').addEventListener('click', function (e) {
      e.stopPropagation();
      self.toggleWebFullscreen();
    });
    this.btnRate.addEventListener('click', function (e) {
      e.stopPropagation();
      self.toggleRateMenu();
    });
    this.volumeInput.addEventListener('input', function () {
      v.muted = false;
      v.volume = Number(this.value) / 100;
    });
    this.volumeInput.addEventListener('click', function (e) {
      e.stopPropagation();
    });

    /* ---- 进度条：点击 / 拖动 ---- */
    function ratioFromEvent(e, node) {
      var rect = node.getBoundingClientRect();
      var clientX = e.touches && e.touches[0] ? e.touches[0].clientX : e.clientX;
      var ratio = (clientX - rect.left) / rect.width;
      return Math.max(0, Math.min(1, ratio));
    }

    function seekPreview(e) {
      var ratio = ratioFromEvent(e, self.track);
      var time = ratio * (v.duration || 0);
      self.preview.style.left = ratio * 100 + '%';
      self.preview.textContent = util.formatDuration(time);
      self._draggingRatio = ratio;
      self.playedBar.style.width = ratio * 100 + '%';
      self.thumb.style.left = ratio * 100 + '%';
    }

    this.progress.addEventListener('mousedown', function (e) {
      e.preventDefault();
      e.stopPropagation();
      self._dragging = true;
      self.progress.classList.add('mp__progress--dragging');
      seekPreview(e);
      var onMove = function (ev) {
        seekPreview(ev);
      };
      var onUp = function (ev) {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        self._dragging = false;
        self.progress.classList.remove('mp__progress--dragging');
        self.seekToRatio(ratioFromEvent(ev, self.track));
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });

    this.progress.addEventListener(
      'touchstart',
      function (e) {
        e.stopPropagation();
        self._dragging = true;
        seekPreview(e);
      },
      { passive: true }
    );
    this.progress.addEventListener(
      'touchmove',
      function (e) {
        e.stopPropagation();
        seekPreview(e);
      },
      { passive: true }
    );
    this.progress.addEventListener('touchend', function (e) {
      e.stopPropagation();
      self._dragging = false;
      var ratio = self._draggingRatio;
      if (ratio !== undefined) self.seekToRatio(ratio);
    });

    // 控制栏上的点击不要冒泡到手势层
    this.controls.addEventListener('mousedown', function (e) {
      e.stopPropagation();
    });
    this.controls.addEventListener('touchstart', function (e) {
      e.stopPropagation();
    });
  };

  /* ================================================================== 手势 */
  Player.prototype._bindGesture = function () {
    if (this.isTouch) this._bindTouchGesture();
    else this._bindMouseGesture();
  };

  Player.prototype._bindMouseGesture = function () {
    var self = this;
    var layer = this.gestureLayer;
    var v = this.video;

    layer.addEventListener('mousedown', function (e) {
      if (e.button !== 0) return;
      self._pressStart = { x: e.clientX, y: e.clientY, at: Date.now(), moved: false };
      self._beginLongPress();
      var onMove = function (ev) {
        if (!self._pressStart) return;
        if (Math.abs(ev.clientX - self._pressStart.x) > 6 || Math.abs(ev.clientY - self._pressStart.y) > 6) {
          self._pressStart.moved = true;
          self._cancelLongPress();
        }
      };
      var onUp = function () {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        var wasLong = self._longPressing;
        self._endLongPress();
        var start = self._pressStart;
        self._pressStart = null;
        if (wasLong || !start) return;
        if (!start.moved && Date.now() - start.at < PCFG.LONG_PRESS_DELAY) {
          // 单击 = 显隐控制栏；双击 = 播放 / 暂停
          self._handleClick();
        }
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });

    // 滚轮调音量
    layer.addEventListener(
      'wheel',
      function (e) {
        e.preventDefault();
        var step = e.deltaY > 0 ? -0.05 : 0.05;
        v.volume = Math.max(0, Math.min(1, v.volume + step));
        v.muted = false;
        self._hint(v.volume === 0 ? 'volume-mute' : v.volume < 0.5 ? 'volume-low' : 'volume-high',
          '音量 ' + Math.round(v.volume * 100) + '%', 800);
      },
      { passive: false }
    );
  };

  /**
   * 区分单击与双击：
   * 单击 -> 显示 / 隐藏控制栏；双击 -> 播放 / 暂停。
   * 单击延后 240ms 执行，用于等待可能到来的第二次点击。
   */
  Player.prototype._handleClick = function () {
    var self = this;
    var now = Date.now();
    if (now - this._lastClickAt < 280) {
      if (this._clickTimer) {
        clearTimeout(this._clickTimer);
        this._clickTimer = null;
      }
      this._lastClickAt = 0;
      this.togglePlay();
      return;
    }
    this._lastClickAt = now;
    this._clickTimer = setTimeout(function () {
      self._clickTimer = null;
      self._toggleControlsVisible();
    }, 240);
  };

  /** 统一的图标 + 文案提示 */
  Player.prototype._hint = function (iconName, text, duration) {
    this.showCenterHint(
      '<span class="mm-icon">' + MM.icon(iconName, 18) + '</span><span>' + text + '</span>',
      duration
    );
  };

  Player.prototype._bindTouchGesture = function () {
    var self = this;
    var layer = this.gestureLayer;
    var v = this.video;

    layer.addEventListener(
      'touchstart',
      function (e) {
        if (e.touches.length > 1) return; // 多指交给系统（缩放等）
        var t = e.touches[0];
        self._gesture = {
          mode: null,
          startX: t.clientX,
          startY: t.clientY,
          lastX: t.clientX,
          lastY: t.clientY,
          startAt: Date.now(),
          startTime: v.currentTime,
          startVolume: v.volume,
          startBrightness: self._brightness,
          ratio: t.clientX < self.container.clientWidth / 2 ? 'left' : 'right'
        };
        self._beginLongPress();

        // 双击检测
        var now = Date.now();
        if (now - self._lastTapAt < 260) {
          self._cancelLongPress();
          self._gesture = null;
          self.togglePlay();
          self._lastTapAt = 0;
          return;
        }
        self._lastTapAt = now;
      },
      { passive: true }
    );

    layer.addEventListener(
      'touchmove',
      function (e) {
        var g = self._gesture;
        if (!g) return;
        var t = e.touches[0];
        var dx = t.clientX - g.startX;
        var dy = t.clientY - g.startY;

        if (!g.mode) {
          if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
          self._cancelLongPress();
          g.mode = Math.abs(dx) > Math.abs(dy) ? 'seek' : g.ratio === 'left' ? 'brightness' : 'volume';
        }
        if (e.cancelable) e.preventDefault();

        if (g.mode === 'seek') {
          var width = self.container.clientWidth || 1;
          var duration = v.duration || 0;
          var target = Math.max(0, Math.min(duration, g.startTime + (dx / width) * duration));
          g.targetTime = target;
          var delta = target - g.startTime;
          self.showCenterHint(
            '<span class="mm-icon">' + MM.icon(delta >= 0 ? 'forward' : 'rewind', 18) + '</span>' +
              '<span>' + (delta >= 0 ? '快进 ' : '快退 ') + util.formatDuration(Math.abs(delta)) +
              '<b>' + util.formatDuration(target) + ' / ' + util.formatDuration(duration) + '</b></span>',
            0
          );
          var ratio = duration ? target / duration : 0;
          self.playedBar.style.width = ratio * 100 + '%';
          self.thumb.style.left = ratio * 100 + '%';
          self.timeCurrent.textContent = util.formatDuration(target);
        } else if (g.mode === 'volume') {
          var range = self.container.clientHeight * 0.9 || PCFG.GESTURE_RANGE;
          var v2 = Math.max(0, Math.min(1, g.startVolume - dy / range));
          v.volume = v2;
          v.muted = v2 === 0;
          self._hint(
            v2 === 0 ? 'volume-mute' : v2 < 0.5 ? 'volume-low' : 'volume-high',
            Math.round(v2 * 100) + '%',
            0
          );
        } else {
          var range2 = self.container.clientHeight * 0.9 || PCFG.GESTURE_RANGE;
          var b = Math.max(0.05, Math.min(1, g.startBrightness - dy / range2));
          self.setBrightness(b);
          self._hint('sun', Math.round(b * 100) + '%', 0);
        }
      },
      { passive: false }
    );

    layer.addEventListener('touchend', function () {
      var g = self._gesture;
      self._endLongPress();
      self._gesture = null;
      self.hideCenterHint();

      if (!g) return;
      var quick = Date.now() - g.startAt < 260;
      if (!g.mode && quick) {
        // 单击：显隐控制栏
        self._toggleControlsVisible();
      } else if (g.mode === 'seek' && g.targetTime !== undefined) {
        try {
          v.currentTime = g.targetTime;
        } catch (e2) {
          /* ignore */
        }
      }
    });

    layer.addEventListener('touchcancel', function () {
      self._endLongPress();
      self._gesture = null;
      self.hideCenterHint();
    });
  };

  /* ------------------------------------------------------- 长按倍速 */
  Player.prototype._beginLongPress = function () {
    var self = this;
    this._cancelLongPress();
    this._longPressTimer = setTimeout(function () {
      self._longPressing = true;
      self.video.playbackRate = PCFG.LONG_PRESS_RATE;
      self.speedBadge.classList.add('mp__speed-badge--show');
      if (self.video.paused) self.video.play();
    }, PCFG.LONG_PRESS_DELAY);
  };

  Player.prototype._cancelLongPress = function () {
    if (this._longPressTimer) {
      clearTimeout(this._longPressTimer);
      this._longPressTimer = null;
    }
  };

  Player.prototype._endLongPress = function () {
    this._cancelLongPress();
    if (this._longPressing) {
      this._longPressing = false;
      this.video.playbackRate = this._rate; // 松开恢复用户选择的倍速
      this.speedBadge.classList.remove('mp__speed-badge--show');
    }
  };

  /* ================================================================== 键盘 */
  Player.prototype._bindKeyboard = function () {
    var self = this;
    this._keyHandler = function (e) {
      if (self._destroyed) return;
      var tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;
      // 只在播放器所在的页面/可视区域内响应
      var v = self.video;
      var handled = true;
      switch (e.key) {
        case ' ':
        case 'k':
        case 'K':
          self.togglePlay();
          break;
        case 'ArrowLeft':
          v.currentTime = Math.max(0, v.currentTime - (e.shiftKey ? 30 : PCFG.SEEK_STEP));
          self._hint('rewind', util.formatDuration(v.currentTime), 700);
          break;
        case 'ArrowRight':
          v.currentTime = Math.min(v.duration || 0, v.currentTime + (e.shiftKey ? 30 : PCFG.SEEK_STEP));
          self._hint('forward', util.formatDuration(v.currentTime), 700);
          break;
        case 'ArrowUp':
          v.volume = Math.min(1, v.volume + 0.05);
          v.muted = false;
          self.showCenterHint('音量 ' + Math.round(v.volume * 100) + '%', 700);
          break;
        case 'ArrowDown':
          v.volume = Math.max(0, v.volume - 0.05);
          self.showCenterHint('音量 ' + Math.round(v.volume * 100) + '%', 700);
          break;
        case 'm':
        case 'M':
          v.muted = !v.muted;
          self.showCenterHint(v.muted ? '已静音' : '取消静音', 700);
          break;
        case 'f':
        case 'F':
          self.toggleFullscreen();
          break;
        case 'w':
        case 'W':
          self.toggleWebFullscreen();
          break;
        case '[':
          self.setRate(Math.max(0.25, Number((self._rate - 0.25).toFixed(2))));
          break;
        case ']':
          self.setRate(Math.min(4, Number((self._rate + 0.25).toFixed(2))));
          break;
        default:
          if (/^[0-9]$/.test(e.key) && v.duration) {
            v.currentTime = (Number(e.key) / 10) * v.duration;
            self.showCenterHint('跳转至 ' + Math.round(Number(e.key) * 10) + '%', 700);
          } else {
            handled = false;
          }
      }
      if (handled) {
        e.preventDefault();
        self._showControls();
      }
    };
    document.addEventListener('keydown', this._keyHandler);
  };

  Player.prototype._bindWindow = function () {
    var self = this;
    this._onVisibility = function () {
      if (document.hidden) self._report(true);
    };
    this._onUnload = function () {
      self._report(true);
    };
    this._onFsChange = function () {
      var on = !!document.fullscreenElement;
      if (!on) {
        self.container.classList.remove('mp--fullscreen');
      }
      if (self.btnFullscreen) {
        self.btnFullscreen.innerHTML = MM.icon(on ? 'fullscreen-exit' : 'fullscreen', 17);
        self.btnFullscreen.title = on ? '退出全屏' : '全屏';
      }
      self._showControls();
    };
    document.addEventListener('visibilitychange', this._onVisibility);
    global.addEventListener('beforeunload', this._onUnload);
    document.addEventListener('fullscreenchange', this._onFsChange);
  };

  /* ================================================================== 播放 */
  Player.prototype.togglePlay = function () {
    if (this.video.paused) this.play();
    else this.pause();
  };

  Player.prototype.play = function () {
    var p = this.video.play();
    if (p && p.catch) {
      p.catch(
        (function (self) {
          return function (err) {
            MM.log('播放被拒绝', err);
            self.bigPlay.style.display = '';
            MM.ui.toast('点击播放按钮开始播放', 'info', 1600);
          };
        })(this)
      );
    }
  };

  Player.prototype.pause = function () {
    this.video.pause();
  };

  Player.prototype.seek = function (seconds) {
    this.video.currentTime = Math.max(0, Math.min(this.video.duration || 0, seconds));
    this._updateProgress();
  };

  Player.prototype.seekToRatio = function (ratio) {
    var duration = this.video.duration || 0;
    this.seek(ratio * duration);
    this._updateProgress();
  };

  Player.prototype.setRate = function (rate) {
    this._rate = rate;
    if (!this._longPressing) this.video.playbackRate = rate;
    this.btnRate.textContent = rate.toFixed(1) + 'x';
    this.showCenterHint('倍速 ' + rate.toFixed(2) + 'x', 900);
    this._closeRateMenu();
  };

  Player.prototype.setBrightness = function (value) {
    this._brightness = value;
    // 浏览器无法修改系统亮度，用黑色遮罩模拟：亮度 1 -> 遮罩全透明
    this.dim.style.opacity = String(Math.max(0, Math.min(0.95, 1 - value)));
  };

  Player.prototype.toggleRateMenu = function () {
    var self = this;
    if (this._rateMenu) {
      this._closeRateMenu();
      return;
    }
    var menu = el('div', 'mp__rate-pop');
    PCFG.RATES.forEach(function (rate) {
      var item = el('div', 'mp__rate-item' + (Math.abs(rate - self._rate) < 0.001 ? ' mp__rate-item--active' : ''), rate.toFixed(2).replace(/0$/, '') + 'x');
      item.onclick = function (e) {
        e.stopPropagation();
        self.setRate(rate);
      };
      menu.appendChild(item);
    });
    this.container.querySelector('.mp__rate').appendChild(menu);
    this._rateMenu = menu;

    setTimeout(function () {
      self._rateMenuClickAway = function (ev) {
        if (!menu.contains(ev.target) && ev.target !== self.btnRate) self._closeRateMenu();
      };
      document.addEventListener('click', self._rateMenuClickAway);
    }, 0);
  };

  Player.prototype._closeRateMenu = function () {
    if (this._rateMenu) {
      if (this._rateMenu.parentNode) this._rateMenu.parentNode.removeChild(this._rateMenu);
      this._rateMenu = null;
    }
    if (this._rateMenuClickAway) {
      document.removeEventListener('click', this._rateMenuClickAway);
      this._rateMenuClickAway = null;
    }
  };

  Player.prototype.toggleFullscreen = function () {
    if (document.fullscreenElement) {
      document.exitFullscreen();
      return;
    }
    if (this._webFullscreen) this.toggleWebFullscreen();
    var root = this.container;
    var request =
      root.requestFullscreen ||
      root.webkitRequestFullscreen ||
      root.webkitEnterFullscreen ||
      root.mozRequestFullScreen ||
      root.msRequestFullscreen;
    if (request) {
      try {
        request.call(root);
      } catch (e) {
        MM.ui.toast('当前浏览器不支持全屏', 'warning');
      }
    } else if (this.video.webkitEnterFullscreen) {
      this.video.webkitEnterFullscreen(); // iOS Safari
    } else {
      MM.ui.toast('当前浏览器不支持全屏', 'warning');
    }
  };

  Player.prototype.toggleWebFullscreen = function () {
    this._webFullscreen = !this._webFullscreen;
    var c = this.container;
    if (this._webFullscreen) {
      c.dataset.prevStyle = c.getAttribute('style') || '';
      c.style.cssText +=
        ';position:fixed;left:0;top:0;right:0;bottom:0;width:100vw;height:100vh;z-index:9999;border-radius:0;';
      document.body.style.overflow = 'hidden';
      this._placeholder = document.createComment('player-anchor');
      c.parentNode.insertBefore(this._placeholder, c);
      document.body.appendChild(c);
    } else {
      c.setAttribute('style', c.dataset.prevStyle || '');
      document.body.style.overflow = '';
      if (this._placeholder && this._placeholder.parentNode) {
        this._placeholder.parentNode.insertBefore(c, this._placeholder);
        this._placeholder.parentNode.removeChild(this._placeholder);
      }
    }
    this._showControls(true);
  };

  /* ============================================================== 控制栏显隐 */
  /**
   * 显示控制栏。
   * @param {boolean} persist true = 常显（暂停 / 播放结束 / 全屏切换时用）；
   *                          否则在播放中延时自动隐藏。
   */
  Player.prototype._showControls = function (persist) {
    this.controls.classList.add('mp__controls--show');
    this._clearHideTimer();
    if (persist) return;
    this._autoHideControls();
  };

  Player.prototype._clearHideTimer = function () {
    if (this._controlsTimer) {
      clearTimeout(this._controlsTimer);
      this._controlsTimer = null;
    }
  };

  Player.prototype._autoHideControls = function () {
    var self = this;
    this._clearHideTimer();
    this._controlsTimer = setTimeout(function () {
      if (!self.video.paused) self.controls.classList.remove('mp__controls--show');
    }, PCFG.HIDE_DELAY);
  };

  /** 单击画面：在「显示」与「隐藏」控制栏之间切换 */
  Player.prototype._toggleControlsVisible = function () {
    if (this.controls.classList.contains('mp__controls--show')) {
      this._clearHideTimer();
      this.controls.classList.remove('mp__controls--show');
    } else {
      this._showControls();
    }
  };

  Player.prototype.showCenterHint = function (html, duration) {
    var self = this;
    this.centerHint.innerHTML = html;
    this.centerHint.classList.add('mp__center-hint--show');
    if (duration > 0) {
      if (this._hintTimer) clearTimeout(this._hintTimer);
      this._hintTimer = setTimeout(function () {
        self.centerHint.classList.remove('mp__center-hint--show');
      }, duration);
    }
  };

  Player.prototype.hideCenterHint = function () {
    if (this._hintTimer) clearTimeout(this._hintTimer);
    this.centerHint.classList.remove('mp__center-hint--show');
  };

  /* ================================================================ 进度渲染 */
  Player.prototype._updateProgress = function () {
    var v = this.video;
    var duration = v.duration || 0;
    var ratio = duration ? Math.max(0, Math.min(1, v.currentTime / duration)) : 0;
    this.playedBar.style.width = ratio * 100 + '%';
    this.thumb.style.left = ratio * 100 + '%';
    this.timeCurrent.textContent = util.formatDuration(v.currentTime);
    if (duration) this.timeDuration.textContent = util.formatDuration(duration);
  };

  Player.prototype._updateLoaded = function () {
    var v = this.video;
    var duration = v.duration || 0;
    if (!duration || !v.buffered || !v.buffered.length) return;
    var end = v.buffered.end(v.buffered.length - 1);
    this.loadedBar.style.width = Math.min(100, (end / duration) * 100) + '%';
  };

  /* ================================================================ 进度上报 */
  Player.prototype._startReportTimer = function () {
    var self = this;
    if (this._reportTimer) return;
    var interval = Number(this.options.reportInterval || MM.config.PLAY_REPORT.INTERVAL) * 1000;
    this._lastReportAt = Date.now();
    this._reportTimer = setInterval(function () {
      if (self.video.paused) return;
      var now = Date.now();
      var elapsed = (now - self._lastReportAt) / 1000;
      self._lastReportAt = now;
      // 只累计真实播放时间（静音也算观看，符合常见业务口径）
      if (elapsed > 0 && elapsed < 60) {
        self._delta += elapsed;
        self._watchAccum += elapsed;
      }
      self._report(false);
    }, interval);
  };

  Player.prototype._stopReportTimer = function () {
    if (this._reportTimer) {
      clearInterval(this._reportTimer);
      this._reportTimer = null;
    }
  };

  Player.prototype._report = function (force) {
    var v = this.video;
    if (!this.options.onReport) return;
    if (!force && this._delta <= 0) return;
    var payload = {
      position: Number(v.currentTime.toFixed(2)),
      duration: Number((v.duration || 0).toFixed(2)),
      delta: Number(Math.min(this._delta, 600).toFixed(2))
    };
    this._delta = 0;
    try {
      this.options.onReport(payload);
    } catch (e) {
      MM.log('上报回调异常', e);
    }
  };

  /** 手动触发一次上报（如页面切走前） */
  Player.prototype.flushReport = function () {
    this._report(true);
  };

  Player.prototype.getState = function () {
    return {
      currentTime: this.video.currentTime,
      duration: this.video.duration || 0,
      paused: this.video.paused,
      volume: this.video.volume,
      muted: this.video.muted,
      rate: this._rate,
      brightness: this._brightness,
      watchSeconds: this._watchAccum
    };
  };

  /* ================================================================== 销毁 */
  Player.prototype.destroy = function () {
    this._destroyed = true;
    this._report(true);
    this._stopReportTimer();
    this._stopPolling && this._stopPolling();
    this._cancelLongPress();
    this._closeRateMenu();
    if (this._controlsTimer) clearTimeout(this._controlsTimer);
    if (this._clickTimer) clearTimeout(this._clickTimer);
    document.removeEventListener('keydown', this._keyHandler);
    document.removeEventListener('visibilitychange', this._onVisibility);
    global.removeEventListener('beforeunload', this._onUnload);
    document.removeEventListener('fullscreenchange', this._onFsChange);
    try {
      this.video.pause();
      this.video.removeAttribute('src');
      this.video.load();
    } catch (e) {
      /* ignore */
    }
  };

  MM.Player = Player;
})(window);
