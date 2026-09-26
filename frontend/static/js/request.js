/* ==========================================================================
   MediaManager —— HTTP 请求封装 + 登录态管理
   - 统一解析后端 {code, msg, data} 响应体
   - 自动附带 Authorization 头
   - 令牌失效自动清理并跳转登录页
   - 提供带进度的上传方法（XHR，fetch 无法拿到上传进度）
   ========================================================================== */
(function (global) {
  'use strict';

  var MM = (global.MM = global.MM || {});
  var util = MM.util;
  var ui = MM.ui;

  /* ---------------------------------------------------------- 登录态存储 */
  var auth = {
    getToken: function () {
      try {
        return global.localStorage.getItem(MM.config.TOKEN_KEY) || '';
      } catch (e) {
        return '';
      }
    },
    setToken: function (token) {
      try {
        global.localStorage.setItem(MM.config.TOKEN_KEY, token || '');
      } catch (e) {
        /* ignore */
      }
    },
    getUser: function () {
      try {
        var raw = global.localStorage.getItem(MM.config.USER_KEY);
        return raw ? JSON.parse(raw) : null;
      } catch (e) {
        return null;
      }
    },
    setUser: function (user) {
      try {
        global.localStorage.setItem(MM.config.USER_KEY, JSON.stringify(user || null));
      } catch (e) {
        /* ignore */
      }
    },
    clear: function () {
      try {
        global.localStorage.removeItem(MM.config.TOKEN_KEY);
        global.localStorage.removeItem(MM.config.USER_KEY);
      } catch (e) {
        /* ignore */
      }
    },
    isLogin: function () {
      return !!auth.getToken();
    },
    isAdmin: function () {
      var u = auth.getUser();
      return !!u && u.role === 'admin';
    }
  };

  /** 跳转登录页（带来源地址，登录后回跳） */
  function redirectToLogin(isAdminPage) {
    var path = isAdminPage ? MM.config.PATHS.adminLogin : MM.config.PATHS.webLogin;
    var back = global.location.pathname + global.location.search;
    if (back.indexOf('login') >= 0) back = '';
    global.location.replace(util.buildUrl(path, back ? { redirect: back } : null));
  }

  function isAdminContext() {
    return global.location.pathname.indexOf('/admin/') === 0;
  }

  /* ---------------------------------------------------------- 错误对象 */
  function ApiError(code, message, data, httpStatus) {
    this.name = 'ApiError';
    this.code = code;
    this.message = message || '请求失败';
    this.data = data;
    this.httpStatus = httpStatus;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  /* ---------------------------------------------------------- 核心请求 */
  function buildUrl(path, params) {
    var url = /^https?:\/\//i.test(path) ? path : MM.config.API_BASE + path;
    return util.buildUrl(url, params);
  }

  function handleUnauthorized() {
    auth.clear();
    if (MM.__redirecting) return;
    MM.__redirecting = true;
    ui.error('登录已过期，请重新登录');
    setTimeout(function () {
      redirectToLogin(isAdminContext());
    }, 600);
  }

  function parseEnvelope(payload, httpStatus) {
    if (!payload || typeof payload !== 'object' || !('code' in payload)) {
      // 非标准响应（如静态文件 404），按状态码处理
      if (httpStatus >= 400) {
        throw new ApiError(httpStatus, 'HTTP ' + httpStatus, null, httpStatus);
      }
      return payload;
    }
    if (Number(payload.code) === 0) return payload.data;
    var err = new ApiError(payload.code, payload.msg, payload.data, httpStatus);
    if ([2001, 2002, 2003, 2005].indexOf(Number(payload.code)) >= 0) {
      handleUnauthorized();
    }
    throw err;
  }

  function request(method, path, options) {
    var opts = options || {};
    var headers = opts.headers ? Object.assign({}, opts.headers) : {};
    var token = auth.getToken();
    if (token) headers.Authorization = 'Bearer ' + token;

    var body = undefined;
    if (opts.data !== undefined && opts.data !== null) {
      if (opts.data instanceof FormData) {
        body = opts.data; // 交给浏览器自行设置 Content-Type
      } else {
        headers['Content-Type'] = 'application/json;charset=utf-8';
        body = JSON.stringify(opts.data);
      }
    }

    var controller = null;
    var timer = null;
    var fetchOptions = {
      method: method,
      headers: headers,
      body: body,
      credentials: 'same-origin'
    };
    if (!opts.noTimeout && global.AbortController) {
      controller = new AbortController();
      fetchOptions.signal = controller.signal;
      timer = setTimeout(function () {
        controller.abort();
      }, opts.timeout || MM.config.REQUEST_TIMEOUT);
    }

    return fetch(buildUrl(path, opts.params), fetchOptions)
      .then(function (res) {
        var status = res.status;
        return res
          .json()
          .catch(function () {
            return null;
          })
          .then(function (payload) {
            return parseEnvelope(payload, status);
          });
      })
      .catch(function (err) {
        if (err instanceof ApiError) throw err;
        if (err && err.name === 'AbortError') {
          throw new ApiError(-1, '请求超时，请检查网络或后端服务', null, 0);
        }
        throw new ApiError(-2, '网络异常：' + (err && err.message ? err.message : '未知错误'), null, 0);
      })
      .then(
        function (data) {
          if (timer) clearTimeout(timer);
          return data;
        },
        function (err) {
          if (timer) clearTimeout(timer);
          throw err;
        }
      );
  }

  var http = {
    get: function (path, params, options) {
      return request('GET', path, Object.assign({ params: params }, options || {}));
    },
    post: function (path, data, options) {
      return request('POST', path, Object.assign({ data: data }, options || {}));
    },
    put: function (path, data, options) {
      return request('PUT', path, Object.assign({ data: data }, options || {}));
    },
    del: function (path, params, options) {
      return request('DELETE', path, Object.assign({ params: params }, options || {}));
    },

    /** 带上传进度的 POST（XHR 实现），onProgress(percent, loaded, total) */
    upload: function (path, formData, onProgress, options) {
      var opts = options || {};
      return new Promise(function (resolve, reject) {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', buildUrl(path), true);
        var token = auth.getToken();
        if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token);
        xhr.timeout = opts.timeout || MM.config.UPLOAD.TIMEOUT;

        if (xhr.upload && onProgress) {
          xhr.upload.onprogress = function (e) {
            if (e.lengthComputable) {
              onProgress(e.loaded / e.total, e.loaded, e.total);
            }
          };
        }
        xhr.onload = function () {
          var payload = null;
          try {
            payload = JSON.parse(xhr.responseText);
          } catch (e) {
            payload = null;
          }
          try {
            resolve(parseEnvelope(payload, xhr.status));
          } catch (err) {
            reject(err);
          }
        };
        xhr.onerror = function () {
          reject(new ApiError(-2, '网络异常，分片上传失败', null, 0));
        };
        xhr.ontimeout = function () {
          reject(new ApiError(-1, '分片上传超时', null, 0));
        };
        xhr.onabort = function () {
          reject(new ApiError(-3, '已取消', null, 0));
        };
        if (opts.signal) {
          opts.signal.addEventListener('abort', function () {
            xhr.abort();
          });
        }
        xhr.send(formData);
      });
    },

    /** 统一错误提示（页面 catch 里调用即可） */
    toastError: function (err) {
      var msg = (err && err.message) || '操作失败';
      ui.error(msg);
      MM.log('API 错误', err);
      return msg;
    },

    ApiError: ApiError
  };

  MM.auth = auth;
  MM.http = http;
  MM.redirectToLogin = redirectToLogin;

  /**
   * 页面级登录守卫。
   * @param {object} options { requireAdmin: bool, redirect: bool }
   * @returns {Promise<object|null>} 用户对象；未登录且 redirect=true 时不返回
   */
  MM.guard = function (options) {
    var opts = options || {};
    var needAdmin = !!opts.requireAdmin;
    if (!auth.isLogin()) {
      if (opts.redirect !== false) redirectToLogin(needAdmin);
      return Promise.resolve(null);
    }
    var user = auth.getUser();
    if (needAdmin && (!user || user.role !== 'admin')) {
      if (opts.redirect !== false) redirectToLogin(true);
      return Promise.resolve(null);
    }
    // 每次进入页面都与服务端核对一次（账号可能被禁用或降权）
    var url = needAdmin ? '/admin/auth/me' : '/auth/me';
    return http
      .get(url)
      .then(function (data) {
        auth.setUser(data);
        return data;
      })
      .catch(function (err) {
        // 401 已由 http 层统一处理
        if (err && [2001, 2002, 2003].indexOf(Number(err.code)) < 0) {
          MM.log('校验登录态失败', err);
        }
        return null;
      });
  };
})(window);
