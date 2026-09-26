/* ==========================================================================
   MediaManager —— 用户端公共 Vue 组件
   注册方式：Object.keys(MM.components).forEach(n => app.component(n, MM.components[n]))
   说明：依赖 Vue 3 完整版（含模板编译器），由 vue.global.prod.js 提供。
   ========================================================================== */
(function (global) {
  'use strict';

  var MM = (global.MM = global.MM || {});
  var util = MM.util;

  var comps = {};

  /* -------------------------------------------------------------- 视频卡片 */
  comps['v-card'] = {
    name: 'VideoCard',
    props: {
      video: { type: Object, required: true },
      progress: { type: Number, default: 0 }
    },
    computed: {
      coverUrl: function () {
        return this.video.cover_url || '';
      },
      gradient: function () {
        return util.coverGradient(this.video.title || this.video.id);
      },
      initials: function () {
        return util.coverInitials(this.video.title);
      },
      durationText: function () {
        return this.video.duration_text || util.formatDuration(this.video.duration);
      },
      viewText: function () {
        return util.formatCount(this.video.view_count) + ' 次播放';
      }
    },
    methods: {
      open: function () {
        util.go(MM.config.PATHS.webDetail, { id: this.video.id });
      },
      onImgError: function (e) {
        e.target.style.display = 'none';
      }
    },
    template: [
      '<div class="v-card" @click="open">',
      '  <div class="v-card__cover">',
      '    <img v-if="coverUrl" :src="coverUrl" :alt="video.title" loading="lazy" @error="onImgError" />',
      '    <div v-if="!coverUrl" class="v-card__placeholder" :style="{ background: gradient }">{{ initials }}</div>',
      '    <span class="v-card__duration">{{ durationText }}</span>',
      '    <div v-if="progress > 0" class="v-card__progress"><span :style="{ width: Math.min(progress,100) + \'%\' }"></span></div>',
      '  </div>',
      '  <div class="v-card__body">',
      '    <div class="v-card__title">{{ video.title }}</div>',
      '    <div class="v-card__meta">',
      '      <span class="mm-tag mm-tag--muted">{{ video.category_name || "未分类" }}</span>',
      '      <span>{{ viewText }}</span>',
      '    </div>',
      '  </div>',
      '</div>'
    ].join('')
  };

  /* ---------------------------------------------------------- 横向视频条目 */
  comps['v-item'] = {
    name: 'VideoItem',
    props: {
      video: { type: Object, required: true },
      index: { type: Number, default: 0 },
      desc: { type: String, default: '' }
    },
    computed: {
      coverUrl: function () {
        return this.video.cover_url || '';
      },
      gradient: function () {
        return util.coverGradient(this.video.title || this.video.id);
      },
      initials: function () {
        return util.coverInitials(this.video.title);
      },
      durationText: function () {
        return this.video.duration_text || util.formatDuration(this.video.duration);
      },
      metaText: function () {
        var parts = [];
        if (this.video.category_name) parts.push(this.video.category_name);
        if (this.video.view_count !== undefined) parts.push(util.formatCount(this.video.view_count) + ' 次播放');
        return parts.join(' · ');
      }
    },
    methods: {
      open: function () {
        util.go(MM.config.PATHS.webDetail, { id: this.video.id });
      },
      onImgError: function (e) {
        e.target.style.display = 'none';
      }
    },
    template: [
      '<div class="v-item" @click="open">',
      '  <div class="v-item__cover">',
      '    <img v-if="coverUrl" :src="coverUrl" :alt="video.title" loading="lazy" @error="onImgError" />',
      '    <div v-else class="v-card__placeholder" :style="{ background: gradient }" style="font-size:15px">{{ initials }}</div>',
      '    <span v-if="index > 0" class="v-item__index">{{ index }}</span>',
      '    <span class="v-card__duration">{{ durationText }}</span>',
      '  </div>',
      '  <div class="v-item__info">',
      '    <div class="v-item__title">{{ video.title }}</div>',
      '    <div class="v-item__desc" v-if="desc">{{ desc }}</div>',
      '    <div class="v-item__desc" v-else-if="video.description">{{ video.description }}</div>',
      '    <div class="v-card__meta"><span>{{ metaText }}</span></div>',
      '  </div>',
      '</div>'
    ].join('')
  };

  /* ---------------------------------------------------------------- 空状态 */
  comps['mm-empty'] = {
    name: 'MmEmpty',
    props: {
      text: { type: String, default: '暂无数据' },
      /** 图标名，取自 MM.icon 的图标集（见 static/js/icons.js） */
      icon: { type: String, default: 'inbox' }
    },
    template: [
      '<div class="mm-empty">',
      '  <div class="mm-empty__icon"><mm-icon :name="icon" :size="42"></mm-icon></div>',
      '  <div class="mm-empty__text">{{ text }}</div>',
      '  <div><slot></slot></div>',
      '</div>'
    ].join('')
  };

  /* ------------------------------------------------------------ 骨架占位卡 */
  comps['v-skeleton'] = {
    name: 'VideoSkeleton',
    props: { count: { type: Number, default: 8 } },
    template: [
      '<div class="mm-grid">',
      '  <div v-for="i in count" :key="i" class="v-card" style="pointer-events:none">',
      '    <div class="v-card__cover mm-skeleton" style="border-radius:0"></div>',
      '    <div class="v-card__body">',
      '      <div class="mm-skeleton" style="height:14px;width:86%"></div>',
      '      <div class="mm-skeleton" style="height:12px;width:52%"></div>',
      '    </div>',
      '  </div>',
      '</div>'
    ].join('')
  };

  /* ------------------------------------------------------------- 分页条 */
  comps['mm-pager'] = {
    name: 'MmPager',
    props: {
      page: { type: Number, default: 1 },
      pages: { type: Number, default: 1 },
      total: { type: Number, default: 0 }
    },
    emits: ['change'],
    computed: {
      range: function () {
        var list = [];
        var total = this.pages;
        var cur = this.page;
        var start = Math.max(1, cur - 2);
        var end = Math.min(total, start + 4);
        start = Math.max(1, end - 4);
        for (var i = start; i <= end; i++) list.push(i);
        return list;
      }
    },
    template: [
      '<div class="mm-pager" v-if="pages > 1">',
      '  <span class="mm-pager__info">共 {{ total }} 条 / {{ pages }} 页</span>',
      '  <button class="mm-btn mm-btn--sm" :disabled="page <= 1" @click="$emit(\'change\', page - 1)">上一页</button>',
      '  <button class="mm-btn mm-btn--sm" v-for="p in range" :key="p"',
      '    :class="{ \'mm-btn--primary\': p === page }" @click="$emit(\'change\', p)">{{ p }}</button>',
      '  <button class="mm-btn mm-btn--sm" :disabled="page >= pages" @click="$emit(\'change\', page + 1)">下一页</button>',
      '</div>'
    ].join('')
  };

  // 合并进全局注册表。
  // 不能写成 `MM.components = comps`——那样会覆盖掉先加载的组件，也会被后加载的
  // layout-web.js / admin-common.js 追加（web-shell / admin-shell）覆盖关系搞乱。
  MM.components = MM.components || {};
  Object.keys(comps).forEach(function (name) {
    MM.components[name] = comps[name];
  });

  /**
   * 一次性注册到 Vue 应用。
   *
   * !! 必须读取 MM.components，而不是本文件闭包里的 comps !!
   * web-shell（layout-web.js）与 admin-shell（admin-common.js）都是在本文件之后
   * 追加到 MM.components 的；若这里只遍历 comps，这两个外壳组件就不会被注册，
   * 页面会以「未识别自定义元素」的形式渲染，导致布局整体塌掉。
   */
  MM.registerComponents = function (app) {
    Object.keys(MM.components).forEach(function (name) {
      app.component(name, MM.components[name]);
    });
  };
})(window);
