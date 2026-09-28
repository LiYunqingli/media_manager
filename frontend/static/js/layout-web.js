/* ==========================================================================
   MediaManager —— 用户端统一外壳（顶栏 + 移动端 Tabbar）
   多页面共用：每个页面把内容放进 <web-shell> 的默认插槽即可，
   顶栏、分类导航、搜索框、主题切换、用户菜单、底部 Tabbar 全部复用。
   ========================================================================== */
(function (global) {
  'use strict';

  var MM = (global.MM = global.MM || {});
  var util = MM.util;

  /* --------------------------------------------------- Vant 能力统一封装
     MM.vant 已统一在 ui.js 中定义（两端共用），此处不再重复定义。 */

  /* ---------------------------------------------------------------- 顶栏 */
  var WebShell = {
    name: 'WebShell',
    props: {
      user: { type: Object, default: function () { return {}; } },
      active: { type: String, default: '' },
      keyword: { type: String, default: '' },
      fluid: { type: Boolean, default: false }
    },
    emits: ['search'],
    data: function () {
      return {
        theme: MM.ui.getTheme(),
        kw: this.keyword,
        categories: [],
        catOpen: false,
        menuOpen: false
      };
    },
    computed: {
      avatarText: function () {
        var name = this.user.nickname || this.user.username || 'U';
        return this.user.avatar_url ? '' : name.slice(0, 1).toUpperCase();
      },
      navActive: function () {
        return this.active;
      },
      /** 下拉里最多展示的分类数（避免分类过多把面板撑爆） */
      navCategories: function () {
        return this.categories.slice(0, 12);
      },
      /** 当前是否停在某个分类相关页面上（分类总览 or 分类详情） */
      catActive: function () {
        return this.active === 'categories' || this.active.indexOf('cat-') === 0;
      },
      /** 移动端 tabbar 高亮索引：分类入口单独占一格（未匹配到任何一格时给 -1 表示不高亮） */
      tabIndex: function () {
        var map = { home: 0, categories: 1, favorites: 2, history: 3, profile: 4 };
        if (this.catActive) return 1;
        return map[this.active] === undefined ? -1 : map[this.active];
      }
    },
    mounted: function () {
      var self = this;
      MM.http
        .get('/client/categories')
        .then(function (list) {
          self.categories = list || [];
        })
        .catch(function () {
          self.categories = [];
        });
      this._onTheme = function () {
        self.theme = MM.ui.getTheme();
      };
      this._onDocClick = function (e) {
        if (self.$el && !self.$el.contains(e.target)) self.catOpen = false;
      };
      this._onKey = function (e) {
        if (e.key === 'Escape') self.catOpen = false;
      };
      global.addEventListener('mm:theme-change', this._onTheme);
      document.addEventListener('click', this._onDocClick);
      document.addEventListener('keydown', this._onKey);
    },
    unmounted: function () {
      global.removeEventListener('mm:theme-change', this._onTheme);
      document.removeEventListener('click', this._onDocClick);
      document.removeEventListener('keydown', this._onKey);
    },
    methods: {
      onTab: function (index) {
        this.go(['home', 'categories', 'favorites', 'history', 'profile'][index] || 'home');
      },
      toggleCat: function () {
        this.catOpen = !this.catOpen;
      },
      goCategories: function () {
        this.catOpen = false;
        util.go(MM.config.PATHS.webCategories);
      },
      goCategory: function (id) {
        this.catOpen = false;
        util.go(MM.config.PATHS.webCategory, { id: id });
      },
      go: function (name) {
        var paths = MM.config.PATHS;
        if (name === 'home') util.go(paths.webHome);
        else if (name === 'categories') util.go(paths.webCategories);
        else if (name === 'favorites') util.go(paths.webFavorites);
        else if (name === 'history') util.go(paths.webHistory);
        else if (name === 'profile') util.go(paths.webProfile);
      },
      submitSearch: function () {
        var kw = (this.kw || '').trim();
        if (!kw) {
          MM.vant.toast('请输入搜索关键词');
          return;
        }
        this.$emit('search', kw);
      },
      toggleTheme: function () {
        this.theme = MM.ui.toggleTheme();
      },
      logout: function () {
        var self = this;
        MM.vant.confirm('确定要退出登录吗？').then(function () {
          MM.auth.clear();
          util.go(MM.config.PATHS.webLogin);
        });
      }
    },
    template: [
      '<div class="web-body">',
      '  <header class="web-header">',
      '    <div class="web-header__inner">',
      '      <div class="brand" @click="go(\'home\')">',
      '        <span class="brand__logo">M</span>',
      '        <span class="brand__name">MediaManager</span>',
      '      </div>',
      '      <nav class="web-nav">',
      '        <span class="web-nav__item" :class="{ \'web-nav__item--active\': navActive === \'home\' }" @click="go(\'home\')">首页</span>',
      '        <div class="web-nav__drop" :class="{ \'web-nav__drop--open\': catOpen }">',
      '          <span class="web-nav__item web-nav__item--drop"',
      '            :class="{ \'web-nav__item--active\': catActive }"',
      '            role="button" tabindex="0" aria-haspopup="true" :aria-expanded="catOpen ? \'true\' : \'false\'"',
      '            @click.stop="toggleCat" @keyup.enter="toggleCat">',
      '            <mm-icon name="grid" :size="14"></mm-icon>',
      '            <span>分类</span>',
      '            <mm-icon class="web-nav__caret" name="chevron-down" :size="12"></mm-icon>',
      '          </span>',
      '          <div class="web-catmenu" v-show="catOpen">',
      '            <div class="web-catmenu__head">',
      '              <span>按分类浏览</span>',
      '              <span class="web-catmenu__all" @click="goCategories">全部分类',
      '                <mm-icon name="chevron-right" :size="12"></mm-icon>',
      '              </span>',
      '            </div>',
      '            <div class="web-catmenu__list" v-if="navCategories.length">',
      '              <span class="web-catmenu__item" v-for="c in navCategories" :key="c.id" @click="goCategory(c.id)">',
      '                <span class="web-catmenu__name">{{ c.name }}</span>',
      '                <span class="web-catmenu__count">{{ c.video_count }}</span>',
      '              </span>',
      '            </div>',
      '            <div class="web-catmenu__empty" v-else>暂无分类</div>',
      '          </div>',
      '        </div>',
      '        <span class="web-nav__item" :class="{ \'web-nav__item--active\': navActive === \'favorites\' }" @click="go(\'favorites\')">收藏</span>',
      '        <span class="web-nav__item" :class="{ \'web-nav__item--active\': navActive === \'history\' }" @click="go(\'history\')">历史</span>',
      '      </nav>',
      '      <div class="web-search">',
      '        <input v-model="kw" placeholder="搜索视频…" @keyup.enter="submitSearch" />',
      '        <button class="web-search__btn" @click="submitSearch" title="搜索" aria-label="搜索">',
      '          <mm-icon name="search" :size="16"></mm-icon>',
      '        </button>',
      '      </div>',
      '      <div class="web-user">',
      '        <button class="theme-toggle" @click="toggleTheme" :title="theme === \'dark\' ? \'切换到亮色\' : \'切换到暗色\'"',
      '          :aria-label="theme === \'dark\' ? \'切换到亮色\' : \'切换到暗色\'">',
      '          <mm-icon :name="theme === \'dark\' ? \'sun\' : \'moon\'" :size="17"></mm-icon>',
      '        </button>',
      '        <div class="mm-avatar" @click="go(\'profile\')" title="个人中心">',
      '          <img v-if="user.avatar_url" :src="user.avatar_url" alt="avatar" />',
      '          <span v-else>{{ avatarText }}</span>',
      '        </div>',
      '        <span class="web-user__name">{{ user.nickname || user.username }}</span>',
      '        <button class="mm-btn mm-btn--sm" @click="logout">退出</button>',
      '      </div>',
      '    </div>',
      '  </header>',
      '  <main class="web-main" :class="{ \'web-main--fluid\': fluid }">',
      '    <slot></slot>',
      '  </main>',
      '  <footer class="web-footer">',
      '    MediaManager 视频管理系统 · 数据来源于本站内容',
      '  </footer>',
      '  <div class="web-tabbar">',
      '    <van-tabbar :model-value="tabIndex" @change="onTab">',
      '      <van-tabbar-item icon="home-o">首页</van-tabbar-item>',
      '      <van-tabbar-item icon="apps-o">分类</van-tabbar-item>',
      '      <van-tabbar-item icon="star-o">收藏</van-tabbar-item>',
      '      <van-tabbar-item icon="clock-o">历史</van-tabbar-item>',
      '      <van-tabbar-item icon="user-o">我的</van-tabbar-item>',
      '    </van-tabbar>',
      '  </div>',
      '</div>'
    ].join('')
  };

  MM.components = MM.components || {};
  MM.components['web-shell'] = WebShell;

  /**
   * 用户端页面启动模板。
   * @param {object} pageOptions Vue 根组件选项（data/methods/computed/mounted/template…）
   * @param {object} bootOptions { guest: bool, mount: string } guest=true 时不做登录校验（登录页用）
   * @returns {Promise<object>} 根组件实例
   */
  MM.bootWeb = function (pageOptions, bootOptions) {
    var opts = bootOptions || {};
    MM.ui.initTheme();

    var app = Vue.createApp(pageOptions);
    var vant = global.vant;
    if (vant) app.use(vant);
    MM.registerComponents(app);

    var instance = app.mount(opts.mount || '#app');

    if (opts.guest) return Promise.resolve(instance);

    // 登录守卫：未登录会被重定向；已登录则刷新一次用户信息（可能被改权限/禁用）
    return MM.guard({ redirect: true }).then(function (user) {
      if (user && instance && 'user' in instance) {
        instance.user = user;
      }
      return instance;
    });
  };
})(window);

