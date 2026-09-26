# 03 · API 接口文档

- 基础前缀：`/api`
- 交互式文档（服务启动后）：`/docs`（Swagger UI）、`/redoc`
- 机器可读规范：`/openapi.json`

## 1. 通用约定

### 1.1 统一响应体

所有接口（含错误）都返回同一结构：

```json
{ "code": 0, "msg": "ok", "data": { } }
```

- `code = 0` 表示成功，其余为业务错误码；
- **HTTP 状态码同时具有语义**（401 / 403 / 404 等），前端主要按 `code` 分支处理；
- 分页数据统一放在 `data` 内。

### 1.2 分页响应结构

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "list": [],
    "total": 128,
    "page": 1,
    "page_size": 20,
    "pages": 7
  }
}
```

部分接口会在 `data` 中附带额外字段（例如分类详情页会带上 `category`）。

### 1.3 认证

除登录接口与健康检查外，全部接口都需要携带 JWT：

```
Authorization: Bearer <token>
```

或使用查询参数（用于 `<video>` 标签、WebSocket 等无法自定义请求头的场景）：

```
?token=<token>
```

令牌默认有效期 7 天（`security.token_expire_minutes`）。**每次请求都会查库确认账号状态**，
因此管理员改权限、禁用账号会立即生效，无需等令牌过期。

### 1.4 错误码表

| code | 含义 | 典型场景 |
| --- | --- | --- |
| 0 | 成功 | — |
| 1001 | 参数错误 | 必填缺失、格式不符（`msg` 会指出具体字段） |
| 1002 | 非法请求 | 方法不允许等 |
| 2001 | 未登录 | 缺少令牌 |
| 2002 | 登录已过期 | 令牌 exp 已过 |
| 2003 | 令牌无效 | 签名校验失败、被篡改 |
| 2004 | 用户名或密码错误 | 登录失败 |
| 2005 | 账号被禁用 | 管理员已禁用该账号 |
| 2006 | 账号已存在 | 创建用户时重名 |
| 2007 | 原密码错误 | 修改密码 |
| 3001 | 无操作权限 | 非管理员访问管理端接口 |
| 3002 | 无权访问该分类 | 分类不在可见范围内 |
| 3003 | 无权访问该视频 | 视频被拉黑或所属分类不可见 |
| 4001 | 资源不存在 | 通用 404 |
| 4002 | 用户不存在 | — |
| 4003 | 分类不存在 | — |
| 4004 | 视频不存在 | — |
| 4005 | 上传会话不存在或已过期 | — |
| 4006 | 文件不存在 | 磁盘文件被移动/删除 |
| 5001 | 分类名称已存在 | — |
| 5002 | 分类下仍有视频 | 需 `force=true` 强制删除 |
| 5003 | 分片数据非法 | 序号越界、大小超限、MD5 校验失败 |
| 5004 | 分片合并失败 | 合并后大小与预期不符 |
| 5005 | 分片未上传完整 | 缺失分片 |
| 5006 | 不支持的文件类型 | 扩展名不在白名单 |
| 5007 | 文件超过大小限制 | `storage.max_file_size` |
| 9001 | 服务器内部错误 | 未捕获异常 |
| 9002 | 数据库操作失败 | SQL 异常、连接池耗尽 |
| 9003 | 配置错误 | 缺少必填配置项 |

### 1.5 时间与路径

- 时间字段为 MySQL `DATETIME`，序列化为 `"2026-09-26 11:30:00"`；
- 媒体字段成对出现：`cover`（相对路径，入库值）与 `cover_url`（可直接给 `<img src>` 的地址，形如 `/media/covers/2026/09/x.jpg`）。

---

## 2. 认证接口

### 2.1 登录（用户端 / 管理端通用）

```
POST /api/auth/login
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `username` | string | 是 | 1–64 字符 |
| `password` | string | 是 | 1–128 字符 |

**响应** `data`：

```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 604800,
  "user": { "id": 1, "username": "admin", "role": "admin", "status": 1, "...": "..." }
}
```

失败返回 `code=2004`（账号或密码错误）或 `code=2005`（已禁用）。

### 2.2 管理端登录（额外校验角色）

```
POST /api/admin/auth/login
```

参数同上。若账号不是管理员，返回 `code=3001`。

### 2.3 当前用户

```
GET /api/auth/me          # 用户端
GET /api/admin/auth/me    # 管理端
```

`data` 为完整用户对象，并附带统计：`stats.favorite_count`、`stats.history_count`、`stats.watch_seconds`。

### 2.4 修改资料 / 修改密码

```
PUT /api/auth/profile        { "nickname": "...", "email": "...", "phone": "...", "avatar": "..." }
PUT /api/auth/password       { "old_password": "...", "new_password": "..." }
```

`new_password` 至少 6 位，且不能与原密码相同。

---

## 3. 用户端接口（`/api/client`）

> 全部需要登录。返回内容已按当前用户的可见范围过滤。

### 3.1 首页聚合

```
GET /api/client/home
```

**响应** `data`：

```json
{
  "banners": [],
  "hot": [],
  "latest": [],
  "continue_watch": [],
  "sections": [ { "category": { "id": 1, "name": "电影", "video_count": 12 }, "videos": [] } ]
}
```

| 字段 | 说明 |
| --- | --- |
| `banners` | 轮播候选，取最新上传的前 5 个（不足则用热门补齐） |
| `hot` | 热门推荐（按播放次数） |
| `latest` | 最新上传 |
| `continue_watch` | 「继续观看」：有进度、未看完、观看 ≥3 秒的最近 12 条 |
| `sections` | 每个可见分类一个板块，各带 `business.home_section_size`（默认 12）个视频 |

### 3.2 分类

```
GET /api/client/categories
```

只返回**当前用户可见且启用**的分类，每项带 `video_count`。

```
GET /api/client/categories/{category_id}?page=1&page_size=20&order_by=created_at
```

分类详情 + 该分类下视频分页。`data.category` 为分类对象。分类不可见时返回 `code=3002`。

`order_by` 可选：`created_at`（默认）/ `view_count` / `duration` / `title` / `id`。

### 3.3 视频列表与搜索

```
GET /api/client/videos?page=1&page_size=20&category_id=&keyword=&order_by=created_at
GET /api/client/search?keyword=xxx&page=1&page_size=20
```

均返回视频分页，且只包含可见视频。

### 3.4 视频详情（含相关推荐）

```
GET /api/client/videos/{video_id}
```

**响应** `data`（节选）：

```json
{
  "id": 12,
  "category_id": 1,
  "category_name": "电影",
  "title": "示例影片",
  "description": "……",
  "cover_url": "/media/covers/2026/09/20260926_ab12.jpg",
  "play_url": "/media/videos/2026/09/20260926_ab12.mp4",
  "duration": 5420.5,
  "duration_text": "01:30:20",
  "size_text": "1.24 GB",
  "width": 1920,
  "height": 1080,
  "view_count": 88,
  "favorite_count": 6,
  "favorited": true,
  "history": { "last_position": 120.5, "progress": 2.2, "watch_seconds": 300.0, "finished": 0 },
  "related": []
}
```

`related` 为**相关推荐**：同分类视频优先，不足时用「其他分类高播放量视频」补齐，
条数取 `business.related_limit`（默认 8）。推荐结果同样经过可见性过滤。

**这是"在合理位置推荐更多相关视频"的主要实现点**：详情页右栏展示同分类热门，
下方网格展示 `related` 全部内容；播放页右栏与底部各有一处推荐。

```
GET /api/client/videos/{video_id}/related?limit=8
```

单独获取相关推荐。

### 3.5 播放前信息

```
GET /api/client/videos/{video_id}/play-info
```

```json
{
  "video_id": 12,
  "play_url": "/media/videos/2026/09/x.mp4",
  "duration": 5420.5,
  "view_count": 88,
  "favorited": false,
  "favorite_count": 6,
  "last_position": 120.5,
  "progress": 2.2,
  "watch_seconds": 300.0,
  "finished": 0,
  "count_threshold": 10.0,
  "heartbeat_interval": 5
}
```

### 3.6 播放心跳上报 ⭐

```
POST /api/client/videos/{video_id}/play-report
```

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `segment_id` | string | 8–40 字符，前端每次进入播放页生成一次（会话 ID） |
| `position` | float | 当前播放位置（秒） |
| `duration` | float | 视频总时长（秒），0 表示未知 |
| `delta` | float | **本次上报新增的真实播放秒数**，0–600（超出会被夹紧） |

**响应** `data`：

```json
{
  "video_id": 12,
  "view_count": 89,
  "counted": true,
  "session_seconds": 15.2,
  "threshold": 10.0,
  "progress": 2.4,
  "finished": 0,
  "saved_position": 130.7
}
```

- `counted=true` 表示**本次心跳刚好触发了播放次数 +1**（同一会话只会发生一次）；
- 客户端应在 `playing` 状态下每 `heartbeat_interval` 秒上报一次，并在暂停、页面隐藏、
  离开页面前各补一次。

### 3.7 收藏

```
GET    /api/client/favorites?page=1&page_size=20      # 我的收藏
POST   /api/client/favorites/{video_id}               # 收藏（幂等）
DELETE /api/client/favorites/{video_id}               # 取消收藏
POST   /api/client/favorites/{video_id}/toggle        # 切换
```

三个写接口的响应一致：

```json
{ "favorited": true, "favorite_count": 7, "video_id": 12 }
```

### 3.8 观看历史

```
GET    /api/client/history?page=1&page_size=20
DELETE /api/client/history/{video_id}       # 删除单条
DELETE /api/client/history                  # 清空
```

历史条目包含 `last_position_text`、`progress`、`watch_seconds`、`finished`、`watched_at`。

### 3.9 个人中心

```
GET /api/client/profile
PUT /api/client/profile            # { nickname, email, phone, avatar }
PUT /api/client/profile/password   # { old_password, new_password }
```

---

## 4. 管理端接口（`/api/admin`）

> 全部需要管理员身份（令牌所属账号 `role=admin`），否则 `code=3001`。

### 4.1 仪表盘统计

```
GET /api/admin/stats/overview
GET /api/admin/stats/trend?days=14
GET /api/admin/stats/top-videos?limit=10
GET /api/admin/stats/system
```

- `overview`：视频/用户/分类/播放/上传任务五组指标 + 运行环境；
- `trend`：近 N 天有效播放会话数与去重用户数，按天聚合；
- `top-videos`：按播放次数排行；
- `system`：应用版本、存储占用、连接池状态、抽帧后端可用性、关键业务参数。

### 4.2 用户管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/admin/users` | 列表。支持 `keyword`、`role`、`status`、`with_rules=true`（附带权限规则） |
| POST | `/api/admin/users` | 创建用户（**系统唯一建号入口**） |
| GET | `/api/admin/users/{id}` | 详情（含 `rules`、`stats`、`visible_category_ids`） |
| PUT | `/api/admin/users/{id}` | 修改昵称/角色/状态/备注等 |
| DELETE | `/api/admin/users/{id}` | 删除（连带清理收藏、历史、权限规则、播放会话） |
| PUT | `/api/admin/users/{id}/password` | 重置密码 `{ new_password }` |
| PUT | `/api/admin/users/{id}/status?status=0\|1` | 启用/禁用 |

创建用户请求体：

```json
{
  "username": "user3",
  "password": "user123",
  "nickname": "新用户",
  "role": "user",
  "status": 1,
  "email": "",
  "phone": "",
  "remark": "演示账号",
  "allow_category_ids": [1, 3]
}
```

> 安全约束：不能删除自己；不能删除或禁用**最后一个启用的管理员**。

### 4.3 用户可见性权限 ⭐（需求 10）

```
GET /api/admin/users/{user_id}/permissions
PUT /api/admin/users/{user_id}/permissions
```

`PUT` 采用**整体覆盖式保存**，请求体：

```json
{
  "allow_category_ids": [1, 3, 5],
  "deny_category_ids": [2],
  "video_allow_ids": [42],
  "video_deny_ids": [7, 9]
}
```

| 字段 | 语义 |
| --- | --- |
| `allow_category_ids` | 分类白名单。**非空**时该用户只能看到这些分类；为空表示不受白名单限制 |
| `deny_category_ids` | 分类黑名单，优先级高于白名单（同一分类不能既白又黑，服务端会自动从黑名单剔除） |
| `video_allow_ids` | 视频强制放行（即使所属分类不可见） |
| `video_deny_ids` | 视频黑名单，**优先级最高**，命中即不可见 |

为了在界面上挑选视频，额外提供：

```
GET /api/admin/users/{user_id}/permissions/videos?category_id=&keyword=&page=1&page_size=10
```

返回的视频条目会带一个 `rule` 字段：`1` 放行、`0` 禁止、`-1` 跟随分类（未单独设置）。

### 4.4 分类管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/admin/categories` | 列表（含隐藏分类与全量视频数） |
| POST | `/api/admin/categories` | 新增 `{ name, description, cover, sort, status }` |
| GET | `/api/admin/categories/{id}` | 详情 |
| PUT | `/api/admin/categories/{id}` | 修改名称/封面/描述/排序/状态 |
| DELETE | `/api/admin/categories/{id}?force=false` | 删除；分类下有视频时需 `force=true`（会把视频全部下架） |
| PUT | `/api/admin/categories/sort/update` | 批量排序 `{ "ids": [3, 1, 2] }`，按数组顺序重写 `sort`（步长 10） |

### 4.5 视频管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/admin/videos` | 列表。支持 `category_id`、`keyword`、`status`、`order_by`、分页 |
| GET | `/api/admin/videos/{id}` | 详情（含 `favorite_count_real`、`file_exists`） |
| PUT | `/api/admin/videos/{id}` | 修改标题/简介/分类/排序/上下架 |
| DELETE | `/api/admin/videos/{id}?remove_file=false` | 删除；`remove_file=true` 时同时删除磁盘文件 |
| POST | `/api/admin/videos/{id}/cover/from-frame` | 从关键帧重抽封面 `{ "seek_seconds": 3 }` |
| PUT | `/api/admin/videos/{id}/cover?cover=covers/2026/09/x.jpg` | 设置自定义封面 |
| POST | `/api/admin/videos/{id}/refresh-meta` | 重新探测时长/分辨率/码率/文件大小 |

### 4.6 分片上传 ⭐（需求 9）

#### ① 初始化（分配）

```
POST /api/admin/upload/init
```

```json
{
  "file_name": "demo.mp4",
  "file_size": 734003200,
  "file_hash": "a1b2c3...",
  "chunk_size": 0,
  "category_id": 1,
  "title": ""
}
```

**响应** `data`：

```json
{
  "upload_id": "9f1c...",
  "instant": false,
  "chunk_size": 5242880,
  "total_chunks": 140,
  "total_size": 734003200,
  "stage": "init",
  "stage_text": "已分配上传任务",
  "percent": 0,
  "message": "已分配上传任务"
}
```

`instant=true` 表示命中**秒传**，此时 `video_id` 直接可用，无需后续步骤。
`chunk_size` 传 0 表示使用服务端配置。

#### ② 上传分片

```
POST /api/admin/upload/chunk      (multipart/form-data)
```

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `upload_id` | text | 上传会话 ID |
| `index` | text | 分片序号，从 0 开始 |
| `file` | file | 分片二进制 |
| `chunk_hash` | text | 可选，分片 MD5；提供时服务端会校验 |

响应为最新进度快照（同 ④ 的结构）。**重复上传同一 `index` 会覆盖**。
最后一片通常小于 `chunk_size`，其余分片超长会被拒绝。

#### ③ 进度查询

```
GET /api/admin/upload/{upload_id}/progress?with_indexes=false
```

```json
{
  "upload_id": "9f1c...",
  "file_name": "demo.mp4",
  "stage": "merging",
  "stage_text": "分片合并中",
  "percent": 78.4,
  "total_size": 734003200,
  "total_size_text": "700.00 MB",
  "chunk_size": 5242880,
  "total_chunks": 140,
  "uploaded_chunks": 140,
  "merged_bytes": 680000000,
  "merged_percent": 92.64,
  "speed": 52428800,
  "speed_text": "50.00 MB/s",
  "message": "合并中 648.50 MB / 700.00 MB",
  "error": "",
  "video_id": 0,
  "uploaded_indexes": [0, 1, 2, "..."]
}
```

**阶段与百分比区间**：

| stage | 区间 | 计算方式 |
| --- | --- | --- |
| `init` | 0 | 仅分配 |
| `uploading` | 0 → 70 | 已上传分片数 / 总分片数 |
| `merging` | 70 → 90 | 已合并字节 / 总字节 |
| `probing` | 90 → 95 | 解析元信息 |
| `covering` | 95 → 100 | 抽帧生成封面 |
| `finished` | 100 | 完成，`video_id` 有效 |
| `failed` | — | `error` 字段给出失败原因 |

#### ④ 触发合并

```
POST /api/admin/upload/{upload_id}/merge
```

```json
{
  "category_id": 1,
  "title": "我的视频",
  "description": "",
  "cover": "",
  "sort": 0
}
```

立即返回（`stage=merging`），随后合并 / 探测 / 抽帧在**后台线程**执行。
客户端应改为监听 ③ 的进度或订阅 ⑤ 的 WebSocket。

#### ⑤ 进度实时推送（WebSocket）

```
WS /ws/admin/upload/{upload_id}?token=<jwt>
```

- 令牌校验失败会以关闭码 `4401` 断开；
- 服务端只在快照内容变化时推送（有变化时 0.2 秒一帧，稳定后放慢到最多 2 秒一帧）；
- 阶段变为 `finished` / `failed` 时推送最后一帧并主动关闭；
- 推送体与 ③ 的响应结构完全一致（同样是 `{code, msg, data}` 信封）。

**WebSocket 不可用时前端会自动降级为 1 秒轮询 ③**，两者读同一份快照数据。

#### ⑥ 取消与维护

```
DELETE /api/admin/upload/{upload_id}          # 取消并清理已落盘分片
GET    /api/admin/upload/sessions/list?limit=20   # 最近上传会话（含可续传的中断任务）
POST   /api/admin/upload/sessions/cleanup     # 清理超时未完成会话（默认 24 小时）
```

#### ⑦ 图片直传（封面 / 头像 / 分类图）

```
POST /api/admin/upload/image      (multipart/form-data)
```

| 字段 | 说明 |
| --- | --- |
| `file` | 图片文件，≤20MB |
| `kind` | `cover` / `avatar` / `category`，决定落盘目录 |

```json
{ "path": "covers/2026/09/cover_20260926_ab12.jpg", "url": "/media/covers/...", "size": 20480, "size_text": "20.00 KB" }
```

---

## 5. 静态资源与系统接口

| 路径 | 说明 |
| --- | --- |
| `/media/videos/**` | 视频文件（支持 HTTP Range，可拖动进度条） |
| `/media/covers/**` | 封面图片 |
| `/media/avatars/**` | 头像 |
| `/static/**` | 前端 CSS / JS / vendor 库 |
| `/admin/**` | 管理端页面 |
| `/`（默认）/ `/web/**` | 用户端页面（由 `app.default_site` 决定） |
| `GET /api/health` | 健康检查，返回 MySQL 版本 |
| `GET /api/info` | 应用信息与各入口地址 |

> 分片目录 `storage/chunks`、日志目录 `storage/logs` **不做静态挂载**，
> 挂载点按目录逐个声明，避免暴露中间文件。

---

## 6. 前端调用示例

```js
// 登录
const { token, user } = await MM.http.post('/auth/login', { username, password });

// 首页
const home = await MM.http.get('/client/home');

// 播放心跳（播放器回调里调用）
await MM.http.post(`/client/videos/${id}/play-report`, {
  segment_id: segmentId,
  position: player.video.currentTime,
  duration: player.video.duration,
  delta: 5
});

// 分片上传（直接使用封装好的上传器）
const uploader = new MM.ChunkUploader(file, {
  categoryId: 1,
  title: '我的视频',
  concurrency: 3,
  onProgress: (state) => console.log(state.stage, state.percent, state.speed),
  onFinished: (state) => console.log('完成，videoId =', state.videoId),
  onError: (err) => console.error(err)
});
uploader.start();
```
