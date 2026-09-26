/* ==========================================================================
   MediaManager —— 用户端统一外壳（顶栏 + 移动端 Tabbar）
   多页面共用：每个页面把内容放进 <web-shell> 的默认插槽即可，
   顶栏、分类导航、搜索框、主题切换、用户菜单、底部 Tabbar 全部复用。
   ========================================================================== */
(function (global) {
  'use strict';

  var MM = (global.MM = global.MM || {});
  var util = MM.util;

  /* --------------------------------------------------- Vant 能力统一封装 */
  MM.vant = {
    /** 轻提示：优先用 Vant，缺失时回退到自研 toast */
    toast: function (message, type) {
      var v = global.vant;
      if (v && v.showToast) {
        v.showToast({ message: message, type: type || 'text', duration: 2000 });
      } else {
        MM.ui.toast(message, type === 'fail' ? 'error' : type === 'success' ? 'success' : 'info');
      }
    },
    confirm: function (message, title) {
      var v = global.vant;
      if (v && v.showConfirmDialog) {
        return v.showConfirmDialog({ title: title || '提示', message: message });
      }
      return MM.ui.confirm(message);
    }
  };

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
      global.addEventListener('mm:theme-change', this._onTheme);
    },
    unmounted: function () {
      global.removeEventListener('mm:theme-change', this._onTheme);
    },
    methods: {
      onTab: function (index) {
        this.go(['home', 'favorites', 'history', 'profile'][index] || 'home');
      },
      go: function (name) {
        var paths = MM.config.PATHS;
        if (name === 'home') util.go(paths.webHome);
        else if (name === 'favorites') util.go(paths.webFavorites);
        else if (name === 'history') util.go(paths.webHistory);
        else if (name === 'profile') util.go(paths.webProfile);
      },
      goCategory: function (id) {
        util.go(MM.config.PATHS.webCategory, { id: id });
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
      '        <span class="web-nav__item" v-for="c in categories" :key="c.id"',
      '          :class="{ \'web-nav__item--active\': navActive === \'cat-\' + c.id }"',
      '          @click="goCategory(c.id)">{{ c.name }}</span>',
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
      '    <van-tabbar :model-value="navActive === \'home\' ? 0 : navActive === \'favorites\' ? 1 : navActive === \'history\' ? 2 : navActive === \'profile\' ? 3 : -1"',
      '      @change="onTab">',
      '      <van-tabbar-item icon="home-o">首页</van-tabbar-item>',
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

