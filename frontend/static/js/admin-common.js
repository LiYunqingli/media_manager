/* ==========================================================================
   MediaManager —— 管理端外壳与启动器
   依赖：Vue 3 + Element Plus + @element-plus/icons-vue（均已本地化到 /static/vendor）
   ========================================================================== */
(function (global) {
  'use strict';

  var MM = (global.MM = global.MM || {});
  var util = MM.util;

  /* ------------------------------------------------------------ 菜单定义
     icon 取 Element Plus 图标组件名（element-plus-icons.js 已全局注册） */
  MM.adminMenu = [
    { group: '内容' },
    { key: 'upload', title: '上传视频', icon: 'Upload', path: '/admin/upload.html', badge: '分片' },
    { key: 'videos', title: '视频管理', icon: 'VideoCamera', path: '/admin/videos.html' },
    { key: 'categories', title: '分类管理', icon: 'FolderOpened', path: '/admin/categories.html' },
    { group: '用户' },
    { key: 'users', title: '用户与权限', icon: 'UserFilled', path: '/admin/users.html' },
    { group: '系统' },
    { key: 'index', title: '数据概览', icon: 'DataAnalysis', path: '/admin/index.html' },
    { key: 'settings', title: '系统信息', icon: 'Setting', path: '/admin/settings.html' }
  ];

  /* ------------------------------------------------------ 断点与响应式 mixin
     断点值必须与 admin.css 的媒体查询保持一致，改一处就要改另一处 */
  MM.breakpoint = { mobile: 767, narrow: 1023 };

  function mql(query) {
    return global.matchMedia ? global.matchMedia(query) : null;
  }
  function mqMatch(query, fallbackPx) {
    var m = mql(query);
    if (m) return m.matches;
    // 无 matchMedia 的极端情况：退回按视口宽度判断
    return (global.innerWidth || 1e4) <= fallbackPx;
  }

  MM.mixins = MM.mixins || {};

  /**
   * 管理端响应式 mixin：外壳与所有页面共用。
   * mmIsMobile（≤767px）—— 表格换卡片列表、弹窗单列、描述列表单列；
   * mmIsNarrow（≤1023px）—— 侧栏由固定导航改为抽屉。
   */
  MM.mixins.responsive = {
    data: function () {
      return {
        mmIsMobile: mqMatch('(max-width: ' + MM.breakpoint.mobile + 'px)', MM.breakpoint.mobile),
        mmIsNarrow: mqMatch('(max-width: ' + MM.breakpoint.narrow + 'px)', MM.breakpoint.narrow)
      };
    },
    mounted: function () {
      var self = this;
      this._mq = {
        mobile: mql('(max-width: ' + MM.breakpoint.mobile + 'px)'),
        narrow: mql('(max-width: ' + MM.breakpoint.narrow + 'px)')
      };
      this._onMqMobile = function (e) {
        self.mmIsMobile = e.matches;
      };
      this._onMqNarrow = function (e) {
        self.mmIsNarrow = e.matches;
      };
      if (this._mq.mobile && this._mq.mobile.addEventListener) {
        this._mq.mobile.addEventListener('change', this._onMqMobile);
      }
      if (this._mq.narrow && this._mq.narrow.addEventListener) {
        this._mq.narrow.addEventListener('change', this._onMqNarrow);
      }
    },
    beforeUnmount: function () {
      if (this._mq && this._mq.mobile && this._mq.mobile.removeEventListener) {
        this._mq.mobile.removeEventListener('change', this._onMqMobile);
      }
      if (this._mq && this._mq.narrow && this._mq.narrow.removeEventListener) {
        this._mq.narrow.removeEventListener('change', this._onMqNarrow);
      }
    }
  };

  /* ------------------------------------------------------------ 外壳组件 */
  var AdminShell = {
    name: 'AdminShell',
    mixins: [MM.mixins.responsive],
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
    watch: {
      // 视口回宽（横竖屏切换 / 拉大窗口）时收起抽屉，避免留下一个孤儿遮罩
      mmIsNarrow: function (narrow) {
        if (!narrow) this.closeMobile();
      }
    },
    mounted: function () {
      var self = this;
      this._onTheme = function () {
        self.theme = MM.ui.getTheme();
      };
      global.addEventListener('mm:theme-change', this._onTheme);
      // Esc 收起抽屉；已有弹窗（el-overlay）时不抢按键
      this._onKey = function (e) {
        if (e.key !== 'Escape' || !self.mobileOpen) return;
        if (global.document.querySelector('.el-overlay')) return;
        self.closeMobile();
      };
      global.document.addEventListener('keydown', this._onKey);
      try {
        self.collapsed = global.localStorage.getItem('mm_admin_collapsed') === '1';
      } catch (e) {}
    },
    unmounted: function () {
      global.removeEventListener('mm:theme-change', this._onTheme);
      global.document.removeEventListener('keydown', this._onKey);
      this.closeMobile();
    },
    methods: {
      go: function (path) {
        this.closeMobile();
        global.location.href = path;
      },
      /* 移动端抽屉 */
      toggleMobile: function () {
        this.setMobileOpen(!this.mobileOpen);
      },
      closeMobile: function () {
        this.setMobileOpen(false);
      },
      setMobileOpen: function (open) {
        this.mobileOpen = open;
        // 抽屉展开时锁住页面滚动，否则手指一滑背景就跑了
        try {
          global.document.body.style.overflow = open ? 'hidden' : '';
        } catch (e) {}
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
      '<div class="admin-layout" :class="{ \'admin-layout--collapsed\': collapsed && !mmIsNarrow, \'admin-layout--mobile-open\': mobileOpen }">',
      '  <aside class="admin-side">',
      '    <div class="admin-side__brand">',
      '      <span class="admin-side__logo">M</span>',
      '      <div style="min-width:0">',
      '        <div class="admin-side__title">MediaManager</div>',
      '        <div class="admin-side__sub">视频管理系统</div>',
      '      </div>',
      '      <button class="mm-btn mm-btn--icon admin-side__close" @click="closeMobile"',
      '        title="收起菜单" aria-label="收起菜单">',
      '        <el-icon><Close /></el-icon>',
      '      </button>',
      '    </div>',
      '    <nav class="admin-menu">',
      '      <template v-for="(m, i) in menu" :key="i">',
      '        <div v-if="m.group" class="admin-menu__group">{{ m.group }}</div>',
      '        <div v-else class="admin-menu__item" :class="{ \'admin-menu__item--active\': m.key === active }"',
      '             @click="go(m.path)" :title="m.title">',
      '          <el-icon><component :is="m.icon" /></el-icon><span>{{ m.title }}</span>',
      '          <span v-if="m.badge" class="admin-menu__badge">{{ m.badge }}</span>',
      '        </div>',
      '      </template>',
      '    </nav>',
      '    <div class="admin-side__foot">',
      '      <button class="mm-btn mm-btn--sm mm-btn--block" @click="goWeb">',
      '        <el-icon><TopRight /></el-icon><span>打开用户端</span>',
      '      </button>',
      '    </div>',
      '  </aside>',
      '  <div class="admin-mask" @click="closeMobile"></div>',
      '  <div class="admin-main">',
      '    <header class="admin-topbar">',
      '      <button class="mm-btn mm-btn--icon admin-burger" @click="toggleMobile"',
      '        :aria-expanded="mobileOpen ? \'true\' : \'false\'" aria-label="打开菜单">',
      '        <el-icon><component :is="mobileOpen ? \'Close\' : \'Menu\'" /></el-icon>',
      '      </button>',
      '      <button class="mm-btn mm-btn--icon mm-btn--sm admin-collapse" @click="toggleCollapse" title="折叠菜单" aria-label="折叠菜单">',
      '        <el-icon><Menu /></el-icon>',
      '      </button>',
      '      <div class="admin-topbar__head">',
      '        <div class="admin-topbar__title">{{ title }}</div>',
      '        <div class="admin-topbar__crumb" v-if="crumb">{{ crumb }}</div>',
      '      </div>',
      '      <div class="mm-grow"></div>',
      '      <button class="theme-toggle" @click="toggleTheme"',
      '        :title="theme === \'dark\' ? \'切换到亮色\' : \'切换到暗色\'"',
      '        :aria-label="theme === \'dark\' ? \'切换到亮色\' : \'切换到暗色\'">',
      '        <el-icon v-if="theme === \'dark\'"><Sunny /></el-icon>',
      '        <el-icon v-else><Moon /></el-icon>',
      '      </button>',
      '      <div class="mm-row admin-topbar__user">',
      '        <div class="mm-avatar">{{ avatarText() }}</div>',
      '        <div class="admin-topbar__usertext">',
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
  /* 不能注册为组件的原生标签名（HTML + SVG）。
     @element-plus/icons-vue 里有 6 个图标全小写后正好撞上：
     Filter / Link / Menu / Picture / Select / View。
     这几个要用的话写成 <component :is="'View'" />。 */
  var NATIVE_TAG_NAME = ('a abbr address area article aside audio b base bdi bdo blockquote body br button ' +
    'canvas caption cite code col colgroup data datalist dd del details dfn dialog div dl dt em embed ' +
    'fieldset figcaption figure footer form frame frameset h1 h2 h3 h4 h5 h6 head header hgroup hr html i ' +
    'iframe img input ins kbd label legend li link main map mark marquee menu meta meter nav nobr ' +
    'noscript object ol optgroup option output p param picture plaintext pre progress q rp rt ruby s samp ' +
    'script section select slot small source span strike strong style sub summary sup table tbody td ' +
    'template textarea tfoot th thead time title tr track tt u ul var video wbr ' +
    'svg animate circle clipPath defs desc ellipse feBlend feColorMatrix feGaussianBlur feMerge feOffset ' +
    'filter foreignObject g image line linearGradient marker mask metadata path pattern polygon polyline ' +
    'radialGradient stop switch symbol text textPath tspan use view').split(' ');

  MM.bootAdmin = function (pageOptions, bootOptions) {
    var opts = bootOptions || {};
    MM.ui.initTheme();

    // 每个页面自动带上断点状态（mmIsMobile / mmIsNarrow），与 admin.css 同一套断点
    pageOptions.mixins = (pageOptions.mixins || []).concat([MM.mixins.responsive]);

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
        var icon = global.ElementPlusIconsVue[name];
        app.component(name, icon);
        /* 页面里的模板是 in-DOM 模板，HTML 解析器会把 <VideoCamera /> 小写成
           <videocamera>；Vue 查注册表只试「原名 / 小驼峰 / 大驼峰」三种写法，
           全小写这一种查不到，图标就被当成原生元素渲染成看不见的空标签
           （<videocamera></videocamera>）。补一个全小写别名即可命中。

           但和原生标签同名的那几个不能注册 —— 组件优先级高于原生元素，
           注册了会连原生 <select>/<menu> 都被顶掉；这几个只能写成
           <component :is="'View'" /> 走动态解析。 */
        var lower = name.toLowerCase();
        if (lower !== name && NATIVE_TAG_NAME.indexOf(lower) < 0) {
          app.component(lower, icon);
        }
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
