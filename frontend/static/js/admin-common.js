/* ==========================================================================
   MediaManager —— 管理端外壳与启动器
   依赖：Vue 3 + Element Plus + @element-plus/icons-vue（均已本地化到 /static/vendor）
   ========================================================================== */
(function (global) {
  'use strict';

  var MM = (global.MM = global.MM || {});
  var util = MM.util;

  /* ------------------------------------------------------------ 菜单定义 */
  MM.adminMenu = [
    { group: '内容' },
    { key: 'upload', title: '上传视频', icon: '⬆', path: '/admin/upload.html', badge: '分片' },
    { key: 'videos', title: '视频管理', icon: '🎬', path: '/admin/videos.html' },
    { key: 'categories', title: '分类管理', icon: '🗂', path: '/admin/categories.html' },
    { group: '用户' },
    { key: 'users', title: '用户与权限', icon: '👤', path: '/admin/users.html' },
    { group: '系统' },
    { key: 'index', title: '数据概览', icon: '📊', path: '/admin/index.html' },
    { key: 'settings', title: '系统信息', icon: '⚙', path: '/admin/settings.html' }
  ];

  /* ------------------------------------------------------------ 外壳组件 */
  var AdminShell = {
    name: 'AdminShell',
    props: {
      title: { type: String, default: '' },
      crumb: { type: String, default: '' },
      active: { type: String, default: '' }
    },
    data: function () {
      return {
        theme: MM.ui.getTheme(),
        user: MM.auth.getUser() || {},
        collapsed: false,
        mobileOpen: false,
        menu: MM.adminMenu
      };
    },
    mounted: function () {
      var self = this;
      this._onTheme = function () {
        self.theme = MM.ui.getTheme();
      };
      global.addEventListener('mm:theme-change', this._onTheme);
      try {
        self.collapsed = global.localStorage.getItem('mm_admin_collapsed') === '1';
      } catch (e) {}
    },
    unmounted: function () {
      global.removeEventListener('mm:theme-change', this._onTheme);
    },
    methods: {
      go: function (path) {
        global.location.href = path;
      },
      toggleCollapse: function () {
        this.collapsed = !this.collapsed;
        try {
          global.localStorage.setItem('mm_admin_collapsed', this.collapsed ? '1' : '0');
        } catch (e) {}
      },
      toggleTheme: function () {
        this.theme = MM.ui.toggleTheme();
      },
      logout: function () {
        var self = this;
        MM.ui.confirm('确定退出管理端登录？').then(function (yes) {
          if (!yes) return;
          MM.auth.clear();
          util.go(MM.config.PATHS.adminLogin);
        });
      },
      avatarText: function () {
        var n = this.user.nickname || this.user.username || 'A';
        return n.slice(0, 1).toUpperCase();
      },
      goWeb: function () {
        global.open('/', '_blank');
      }
    },
    template: [
      '<div class="admin-layout" :class="{ \'admin-layout--collapsed\': collapsed, \'admin-layout--mobile-open\': mobileOpen }">',
      '  <aside class="admin-side">',
      '    <div class="admin-side__brand">',
      '      <span class="admin-side__logo">M</span>',
      '      <div style="min-width:0">',
      '        <div class="admin-side__title">MediaManager</div>',
      '        <div class="admin-side__sub">视频管理系统</div>',
      '      </div>',
      '    </div>',
      '    <nav class="admin-menu">',
      '      <template v-for="(m, i) in menu" :key="i">',
      '        <div v-if="m.group" class="admin-menu__group">{{ m.group }}</div>',
      '        <div v-else class="admin-menu__item" :class="{ \'admin-menu__item--active\': m.key === active }"',
      '             @click="go(m.path)" :title="m.title">',
      '          <i>{{ m.icon }}</i><span>{{ m.title }}</span>',
      '          <span v-if="m.badge" class="admin-menu__badge">{{ m.badge }}</span>',
      '        </div>',
      '      </template>',
      '    </nav>',
      '    <div class="admin-side__foot">',
      '      <button class="mm-btn mm-btn--sm mm-btn--block" @click="goWeb">↗ 打开用户端</button>',
      '    </div>',
      '  </aside>',
      '  <div class="admin-mask" @click="mobileOpen = false"></div>',
      '  <div class="admin-main">',
      '    <header class="admin-topbar">',
      '      <button class="mm-btn mm-btn--icon mm-btn--sm" @click="toggleCollapse" title="折叠菜单">☰</button>',
      '      <div>',
      '        <div class="admin-topbar__title">{{ title }}</div>',
      '        <div class="admin-topbar__crumb" v-if="crumb">{{ crumb }}</div>',
      '      </div>',
      '      <div class="mm-grow"></div>',
      '      <button class="theme-toggle" @click="toggleTheme" :title="theme === \'dark\' ? \'切换到亮色\' : \'切换到暗色\'">',
      '        {{ theme === \'dark\' ? \'☀\' : \'☾\' }}',
      '      </button>',
      '      <div class="mm-row" style="gap:8px">',
      '        <div class="web-avatar">{{ avatarText() }}</div>',
      '        <div style="line-height:1.25">',
      '          <div style="font-size:13px">{{ user.nickname || user.username }}</div>',
      '          <div style="font-size:11px;color:var(--text-3)">管理员</div>',
      '        </div>',
      '        <button class="mm-btn mm-btn--sm" @click="logout">退出</button>',
      '      </div>',
      '    </header>',
      '    <div class="admin-content">',
      '      <slot></slot>',
      '    </div>',
      '  </div>',
      '</div>'
    ].join('')
  };

  MM.components = MM.components || {};
  MM.components['admin-shell'] = AdminShell;

  /* ------------------------------------------------------------ 启动器 */
  /**
   * 管理端页面启动。
   * @param {object} pageOptions 根组件选项
   * @param {object} bootOptions { guest: bool }
   */
  MM.bootAdmin = function (pageOptions, bootOptions) {
    var opts = bootOptions || {};
    MM.ui.initTheme();

    var app = Vue.createApp(pageOptions);

    // Element Plus + 中文语言包 + 图标
    if (global.ElementPlus) {
      app.use(global.ElementPlus, {
        locale: global.ElementPlusLocaleZhCn || undefined,
        size: 'default'
      });
    }
    if (global.ElementPlusIconsVue) {
      Object.keys(global.ElementPlusIconsVue).forEach(function (name) {
        app.component(name, global.ElementPlusIconsVue[name]);
      });
    }
    MM.registerComponents(app);

    var instance = app.mount(opts.mount || '#app');

    if (opts.guest) return Promise.resolve(instance);

    return MM.guard({ requireAdmin: true, redirect: true }).then(function (user) {
      if (user && instance && 'user' in instance) instance.user = user;
      return instance;
    });
  };
})(window);
