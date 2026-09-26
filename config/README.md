# 配置文件说明

本目录集中存放系统全部可配置项。

| 文件 | 作用 | 是否入库 |
| --- | --- | --- |
| `config.yaml` | 主配置，唯一被程序读取的文件 | 是 |
| `README.md` | 本说明 | 是 |

## 使用方式

程序启动时按以下顺序定位配置：

1. 环境变量 `MM_CONFIG` 指定的绝对/相对路径；
2. 项目根目录下的 `config/config.yaml`；
3. 均未找到则抛错退出。

启动示例：

```bash
# 使用默认配置
python backend/run.py

# 指定其他配置
MM_CONFIG=D:/conf/prod.yaml python backend/run.py
```

## 环境变量占位符

配置值支持 `${ENV_NAME:default}` 语法，运行时会用环境变量替换，未设置时使用默认值。
这样可以避免把数据库密码写进版本库。

```yaml
database:
  password: "${MM_DB_PASSWORD:123456}"
```

```bash
# Linux / macOS
export MM_DB_PASSWORD='prod-strong-password'
# Windows PowerShell
$env:MM_DB_PASSWORD = 'prod-strong-password'
```

## 关键配置速查

| 配置项 | 说明 |
| --- | --- |
| `app.host` / `app.port` | 监听地址与端口，局域网手机访问需 `0.0.0.0` |
| `app.cors_origins` | 前后端分离部署时的跨域白名单 |
| `database.*` | MySQL 连接信息与连接池 |
| `security.secret_key` | JWT 签名密钥，**上线必须修改** |
| `security.token_expire_minutes` | 登录有效期（分钟） |
| `storage.root` | 媒体文件根目录 |
| `upload.chunk_size` | 分片大小（字节），前端切分依据 |
| `media.backend` | 抽帧后端：`auto` / `av` / `cv2` / `builtin` |
| `business.view_count_threshold_seconds` | 播放次数统计阈值，默认 10 秒 |

## 路径约定

`storage.root` 若为相对路径，则相对于**项目根目录**（即 `backend/` 与 `frontend/` 的父目录）解析，
不依赖当前工作目录，避免从不同位置启动时目录错乱。

## 修改后生效

配置在进程启动时加载并缓存。修改后需重启服务。
（若需热更新，可在 `backend/app/core/config.py` 中把 `load_config()` 的缓存去掉。）
