"""启动脚本。

使用前请确认：
1. 已执行 ``sql/media_manager.sql`` 建库；
2. 已按需修改 ``config/config.yaml`` 中的数据库连接；
3. 已安装依赖 ``pip install -r backend/requirements.txt``。

启动::

    python backend/run.py            # 读取 config/config.yaml
    python backend/run.py --port 9000 --host 127.0.0.1
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 保证以 `python backend/run.py` 方式启动时也能 import app.*
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MediaManager 视频管理系统后端")
    parser.add_argument("--host", default=None, help="监听地址，默认取配置 app.host")
    parser.add_argument("--port", type=int, default=None, help="监听端口，默认取配置 app.port")
    parser.add_argument("--reload", action="store_true", help="开启热重载（开发用）")
    parser.add_argument("--workers", type=int, default=1, help="工作进程数（多进程时禁用 reload）")
    parser.add_argument("--log-level", default=None, help="日志级别: debug/info/warning/error")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    from app.core.config import get_settings
    from app.core.logger import setup_logging

    settings = get_settings()
    setup_logging()

    import uvicorn

    host = args.host or str(settings.get("app.host", "0.0.0.0"))
    port = int(args.port or settings.get("app.port", 8000))
    reload = bool(args.reload or settings.get("dev.reload", False))
    log_level = (args.log_level or str(settings.get("log.level", "info"))).lower()

    if args.workers > 1 and reload:
        print("⚠️  --workers 与 --reload 不能同时使用，已自动关闭 reload")
        reload = False

    print(f"启动 MediaManager -> http://{host}:{port}  (管理端 /admin/, 用户端 /)")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(BACKEND_DIR / "app")] if reload else None,
        workers=args.workers if not reload else None,
        log_level=log_level,
        app_dir=str(BACKEND_DIR),
    )


if __name__ == "__main__":
    main()
