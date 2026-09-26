/* ==========================================================================
   MediaManager —— 分片上传器（前端）
   流程：文件签名 → 分配任务 → 并发分片上传 → 触发合并 → 订阅合并/处理进度
   特性：
   - 并发上传（默认 3 片）+ 失败重试（指数退避）
   - 断点续传：init 时服务端返回已上传分片序号，自动跳过
   - 秒传：文件签名命中已有视频则直接完成
   - 全程进度：分片进度 / 合并进度 / 探测与抽帧阶段进度，均由服务端下发
   ========================================================================== */
(function (global) {
  'use strict';

  var MM = (global.MM = global.MM || {});
  var util = MM.util;
  var cfg = MM.config.UPLOAD;

  /* ------------------------------------------------------ 文件签名（弱 hash）*/
  function fileSignature(file) {
    var seed = [file.name, file.size, file.lastModified || 0].join('|');
    // 无 SubtleCrypto 时退化为字符串签名（仍可用于秒传判断，只是碰撞概率略高）
    if (!global.crypto || !global.crypto.subtle || !global.FileReader) {
      return Promise.resolve('s' + simpleHash(seed + file.type));
    }
    var sliceSize = 1024 * 1024;
    var head = file.slice(0, sliceSize);
    var tail = file.size > sliceSize * 2 ? file.slice(file.size - sliceSize) : null;

    return new Promise(function (resolve) {
      var reader = new FileReader();
      reader.onload = function () {
        var bytes = reader.result;
        var extra = tail ? '|tail' + tail.size : '';
        var buf = new Uint8Array(bytes.byteLength);
        buf.set(new Uint8Array(bytes));
        global.crypto.subtle
          .digest('SHA-256', buf)
          .then(function (digest) {
            var hex = Array.prototype.map
              .call(new Uint8Array(digest), function (b) {
                return ('0' + b.toString(16)).slice(-2);
              })
              .join('');
            resolve(hex.slice(0, 56) + ('0000' + (file.size % 65536).toString(16)).slice(-4));
          })
          .catch(function () {
            resolve('s' + simpleHash(seed + extra));
          });
      };
      reader.onerror = function () {
        resolve('s' + simpleHash(seed));
      };
      reader.readAsArrayBuffer(head);
    });
  }

  function simpleHash(text) {
    var hash = 0;
    for (var i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) >>> 0;
    return hash.toString(16).padStart(8, '0') + '|' + text.length;
  }

  /* ------------------------------------------------------------- 上传器 */
  function ChunkUploader(file, options) {
    this.file = file;
    this.options = options || {};
    this.state = {
      fileName: file.name,
      fileSize: file.size,
      uploadId: '',
      stage: 'pending',
      percent: 0,
      chunkSize: 0,
      totalChunks: 0,
      uploadedChunks: 0,
      uploadedSet: {},
      mergedBytes: 0,
      mergedPercent: 0,
      speed: 0,
      message: '等待上传',
      error: '',
      videoId: 0,
      instant: false
    };
    this._paused = false;
    this._cancelled = false;
    this._ws = null;
    this._mergeStarted = false;
    this._bytesSent = 0;
    this._speedTimer = null;
    this._lastBytes = 0;
    this._lastTs = 0;
  }

  ChunkUploader.prototype._emit = function (patch) {
    if (patch) Object.assign(this.state, patch);
    if (this.options.onProgress) {
      try {
        this.options.onProgress(this.state, this);
      } catch (e) {
        MM.log('onProgress 回调异常', e);
      }
    }
  };

  /* ------------------------------------------------------------ 启动 */
  ChunkUploader.prototype.start = function () {
    var self = this;
    self._emit({ stage: 'hashing', message: '正在计算文件特征…' });
    self._startSpeedTimer();

    return fileSignature(self.file)
      .then(function (hash) {
        self._emit({ stage: 'init', message: '正在分配上传任务…' });
        return MM.http.post('/admin/upload/init', {
          file_name: self.file.name,
          file_size: self.file.size,
          file_hash: hash,
          chunk_size: self.options.chunkSize || 0,
          category_id: self.options.categoryId || 0,
          title: self.options.title || ''
        });
      })
      .then(function (data) {
        self.state.uploadId = data.upload_id;
        self.state.chunkSize = data.chunk_size;
        self.state.totalChunks = data.total_chunks;

        if (data.instant) {
          self._emit({
            stage: 'finished',
            percent: 100,
            instant: true,
            videoId: data.video_id,
            message: '文件已存在，秒传完成'
          });
          self._stopSpeedTimer();
          if (self.options.onFinished) self.options.onFinished(self.state);
          return null;
        }

        self._emit({
          stage: 'uploading',
          message: '已分配 ' + data.total_chunks + ' 个分片，每片 ' + util.formatSize(data.chunk_size)
        });
        return self._resumeUpload();
      })
      .catch(function (err) {
        self._fail(err);
      });
  };

  /* -------------------------------------------------- 续传检查 + 分片上传 */
  ChunkUploader.prototype._resumeUpload = function () {
    var self = this;
    return MM.http
      .get('/admin/upload/' + self.state.uploadId + '/progress', { with_indexes: true })
      .then(function (data) {
        var exist = {};
        (data.uploaded_indexes || []).forEach(function (i) {
          exist[i] = true;
        });
        self.state.uploadedSet = exist;
        self.state.uploadedChunks = Object.keys(exist).length;
        if (self.state.uploadedChunks > 0) {
          self._emit({
            message: '检测到已上传 ' + self.state.uploadedChunks + ' 片，继续上传剩余分片'
          });
        }
        return self._uploadChunks();
      })
      .then(function () {
        if (self._cancelled) return null;
        return self._merge();
      });
  };

  ChunkUploader.prototype._pendingIndexes = function () {
    var list = [];
    for (var i = 0; i < this.state.totalChunks; i++) {
      if (!this.state.uploadedSet[i]) list.push(i);
    }
    return list;
  };

  ChunkUploader.prototype._uploadChunks = function () {
    var self = this;
    var queue = self._pendingIndexes();
    var concurrency = Math.max(1, Number(this.options.concurrency) || cfg.CONCURRENCY);
    var cursor = 0;

    if (!queue.length) return Promise.resolve();

    return new Promise(function (resolve, reject) {
      var finished = 0;
      var total = queue.length;
      var failed = null;

      function next() {
        if (self._cancelled) return reject(new MM.http.ApiError(-3, '已取消'));
        if (failed) return;
        if (cursor >= total && finished >= total) return resolve();
        if (cursor >= total) return;
        var index = queue[cursor++];
        uploadOne(index)
          .then(function () {
            finished++;
            self._recalcUploadPercent();
            if (finished >= total) resolve();
            else next();
          })
          .catch(function (err) {
            if (self._paused && err && err.code === -3) {
              // 暂停导致的中断不算失败
              return;
            }
            failed = err;
            reject(err);
          });
      }

      function uploadOne(index) {
        return self._uploadChunkWithRetry(index);
      }

      for (var k = 0; k < Math.min(concurrency, total); k++) next();
    });
  };

  ChunkUploader.prototype._uploadChunkWithRetry = function (index) {
    var self = this;
    var attempt = 0;
    var maxRetry = Number(this.options.retry) || cfg.RETRY;

    function attemptOnce() {
      if (self._paused || self._cancelled) {
        return Promise.reject(new MM.http.ApiError(-3, '已取消'));
      }
      var start = index * self.state.chunkSize;
      var end = Math.min(start + self.state.chunkSize, self.file.size);
      var blob = self.file.slice(start, end);
      var form = new FormData();
      form.append('upload_id', self.state.uploadId);
      form.append('index', String(index));
      form.append('file', blob, self.file.name + '.part' + index);

      return MM.http
        .upload('/admin/upload/chunk', form, null, { timeout: cfg.TIMEOUT })
        .then(function (data) {
          self.state.uploadedSet[index] = true;
          self.state.uploadedChunks = data.uploaded_chunks;
          self.state.percent = data.percent;
          self.state.speed = data.speed || self.state.speed;
          self.state.message = data.message;
          self._bytesSent += blob.size;
          self._emit();
          return data;
        })
        .catch(function (err) {
          if (self._paused || self._cancelled) throw err;
          if (attempt < maxRetry) {
            attempt++;
            var delay = cfg.RETRY_BASE * Math.pow(2, attempt - 1);
            MM.log('分片 ' + index + ' 第 ' + attempt + ' 次重试（' + delay + 'ms 后）');
            self._emit({ message: '分片 ' + index + ' 上传失败，正在重试 ' + attempt + '/' + maxRetry });
            return util.sleep(delay).then(attemptOnce);
          }
          throw err;
        });
    }

    return attemptOnce();
  };

  ChunkUploader.prototype._recalcUploadPercent = function () {
    var s = this.state;
    if (!s.totalChunks) return;
    // 上传阶段占整体 0-70%，与后端保持一致
    var ratio = s.uploadedChunks / s.totalChunks;
    s.percent = Math.round(ratio * 70 * 100) / 100;
    s.message = '已上传 ' + s.uploadedChunks + '/' + s.totalChunks + ' 片';
    this._emit();
  };

  /* ------------------------------------------------------------ 合并 */
  ChunkUploader.prototype._merge = function () {
    var self = this;
    if (self._mergeStarted) return Promise.resolve();
    self._mergeStarted = true;

    self._emit({ stage: 'merging', percent: 70, message: '分片上传完成，开始合并…' });

    // 先连 WebSocket，避免错过早期进度
    self._openSocket();

    return MM.http
      .post('/admin/upload/' + self.state.uploadId + '/merge', {
        category_id: self.options.categoryId,
        title: self.options.title || '',
        description: self.options.description || '',
        cover: self.options.cover || '',
        sort: self.options.sort || 0
      })
      .then(function (data) {
        self._applyServerState(data);
        return null;
      })
      .catch(function (err) {
        self._fail(err);
      });
  };

  ChunkUploader.prototype._openSocket = function () {
    var self = this;
    if (self._ws) return;
    var url =
      MM.config.WS_BASE +
      '/ws/admin/upload/' +
      self.state.uploadId +
      '?token=' +
      encodeURIComponent(MM.auth.getToken());
    var ws;
    try {
      ws = new WebSocket(url);
    } catch (e) {
      MM.log('WebSocket 不可用，回退轮询');
      self._startPolling();
      return;
    }
    self._ws = ws;

    ws.onmessage = function (event) {
      var payload;
      try {
        payload = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      if (payload && payload.data) self._applyServerState(payload.data);
    };
    ws.onerror = function () {
      MM.log('WebSocket 出错，回退轮询');
    };
    ws.onclose = function () {
      self._ws = null;
      // 未结束时靠轮询兜底
      if (
        ['finished', 'failed'].indexOf(self.state.stage) < 0 &&
        self.state.uploadId &&
        !self._cancelled
      ) {
        self._startPolling();
      }
    };
  };

  ChunkUploader.prototype._startPolling = function () {
    var self = this;
    if (self._pollTimer) return;
    self._pollTimer = setInterval(function () {
      if (!self.state.uploadId || self._cancelled) return;
      MM.http
        .get('/admin/upload/' + self.state.uploadId + '/progress')
        .then(function (data) {
          self._applyServerState(data);
        })
        .catch(function (err) {
          MM.log('轮询进度失败', err);
        });
    }, 1000);
  };

  ChunkUploader.prototype._stopPolling = function () {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  };

  ChunkUploader.prototype._applyServerState = function (data) {
    var s = this.state;
    s.stage = data.stage || s.stage;
    s.percent = typeof data.percent === 'number' ? data.percent : s.percent;
    s.mergedBytes = data.merged_bytes || 0;
    s.mergedPercent = data.merged_percent || 0;
    s.totalChunks = data.total_chunks || s.totalChunks;
    s.chunkSize = data.chunk_size || s.chunkSize;
    s.uploadedChunks = data.uploaded_chunks || s.uploadedChunks;
    s.message = data.message || s.message;
    s.error = data.error || '';
    s.videoId = data.video_id || s.videoId;
    if (data.speed) s.speed = data.speed;

    this._stopSpeedTimer();
    this._emit();

    if (s.stage === 'finished') {
      this._stopPolling();
      this._closeSocket();
      if (this.options.onFinished) this.options.onFinished(s);
    } else if (s.stage === 'failed') {
      this._stopPolling();
      this._closeSocket();
      if (this.options.onError) this.options.onError(new Error(s.error || '处理失败'), s);
    }
  };

  /* ------------------------------------------------------- 速度统计 */
  ChunkUploader.prototype._startSpeedTimer = function () {
    var self = this;
    if (self._speedTimer) return;
    self._lastTs = Date.now();
    self._speedTimer = setInterval(function () {
      var now = Date.now();
      var elapsed = (now - self._lastTs) / 1000;
      if (elapsed <= 0) return;
      // 合并阶段的字节量由服务端提供
      var current = self.state.stage === 'uploading' ? self._bytesSent : self.state.mergedBytes;
      var delta = current - self._lastBytes;
      self._lastBytes = current;
      self._lastTs = now;
      if (delta > 0) {
        self.state.speed = Math.round(delta / elapsed);
        self._emit();
      }
    }, 800);
  };

  ChunkUploader.prototype._stopSpeedTimer = function () {
    if (this._speedTimer) {
      clearInterval(this._speedTimer);
      this._speedTimer = null;
    }
  };

  /* ------------------------------------------------------- 控制方法 */
  ChunkUploader.prototype.pause = function () {
    this._paused = true;
    this._emit({ message: '已暂停（可继续）' });
  };

  ChunkUploader.prototype.resume = function () {
    if (!this._paused) return;
    this._paused = false;
    var self = this;
    self._emit({ message: '继续上传…' });
    self._uploadChunks()
      .then(function () {
        return self._merge();
      })
      .catch(function (err) {
        self._fail(err);
      });
  };

  ChunkUploader.prototype.cancel = function () {
    var self = this;
    self._cancelled = true;
    self._stopSpeedTimer();
    self._stopPolling();
    self._closeSocket();
    if (!self.state.uploadId) return Promise.resolve();
    return MM.http
      .del('/admin/upload/' + self.state.uploadId)
      .catch(function () {
        /* 取消失败不阻塞 UI */
      })
      .then(function () {
        self._emit({ stage: 'cancelled', message: '已取消' });
      });
  };

  ChunkUploader.prototype._closeSocket = function () {
    if (this._ws) {
      try {
        this._ws.close();
      } catch (e) {
        /* ignore */
      }
      this._ws = null;
    }
  };

  ChunkUploader.prototype._fail = function (err) {
    var self = this;
    var msg = (err && err.message) || '上传失败';
    self._stopSpeedTimer();
    self._stopPolling();
    self._closeSocket();
    self._emit({ stage: 'failed', error: msg, message: '上传失败：' + msg });
    if (self.options.onError) self.options.onError(err, self.state);
  };

  MM.ChunkUploader = ChunkUploader;
})(window);
