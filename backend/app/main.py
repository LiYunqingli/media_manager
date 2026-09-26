"""FastAPI 应用装配入口。

职责：
1. 加载配置、初始化日志与目录；
2. 注册中间件、异常处理器、路由；
3. 挂载静态资源（媒体文件 + 前端页面）。

启动方式（**由使用者自行执行**）::

    python backend/run.py
    # 或
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.api.ws import router as ws_router
from app.core.config import get_settings
from app.core.logger import get_logger, setup_logging
from app.core.response import register_exception_handlers
from app.db.pool import close_pool, get_pool

logger = get_logger("main")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动/关闭钩子。"""
    settings = get_settings()
    settings.ensure_dirs()
    logger.info("=" * 72)
    logger.info("%s v%s 启动中", settings.get("app.name"), settings.get("app.version"))
    logger.info("配置文件: %s", settings.source)
    logger.info("存储目录: %s", settings.storage_root)
    try:
        get_pool()  # 预热数据库连接池，尽早暴露配置错误
    except Exception as exc:  # noqa: BLE001
        logger.error("数据库连接失败，请检查 config.yaml 中的 database 配置: %s", exc)
    logger.info("管理端: http://%s:%s/admin/", settings.get("app.host"), settings.get("app.port"))
    logger.info("用户端: http://%s:%s/", settings.get("app.host"), settings.get("app.port"))
    logger.info("API 文档: http://%s:%s/docs", settings.get("app.host"), settings.get("app.port"))
    logger.info("=" * 72)

    yield

    close_pool()
    logger.info("%s 已停止", settings.get("app.name"))


class _FreshStaticFiles(StaticFiles):
    """前端资源专用静态服务：附加 ``Cache-Control: no-cache``。

    前端 JS/CSS 的引用不带哈希指纹。当响应缺少 ``Cache-Control`` 时，浏览器会按
    ``Last-Modified`` 做「启发式缓存」，于是**改动后页面仍在执行旧脚本**——典型症状
    就是已修的报错在用户不硬刷新时依旧复现（要按 Ctrl+F5 才好）。

    ``no-cache`` 的含义是「使用缓存前必须先向服务器校验」，配合 ETag / 304 几乎
    没有额外开销，但能保证前端改动即时生效。媒体文件仍用普通 ``StaticFiles``，
    大文件应当被浏览器正常缓存。
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("cache-control", "no-cache")
        return response


def _mount_frontend(app: FastAPI, settings) -> None:
    """挂载前端页面与静态资源。

    路由优先级由注册顺序决定：API 与 WS 先注册，前端挂载最后注册，
    因此 ``/api/**`` 不会被静态挂载吞掉。
    """
    static_dir = FRONTEND_DIR / "static"
    admin_dir = FRONTEND_DIR / "admin"
    web_dir = FRONTEND_DIR / "web"

    if static_dir.exists():
        app.mount("/static", _FreshStaticFiles(directory=str(static_dir)), name="static")

        # 浏览器默认会请求 /favicon.ico，指向内置 SVG 图标，避免无意义的 404
        @app.get("/favicon.ico", include_in_schema=False)
        def _favicon() -> RedirectResponse:
            return RedirectResponse(url="/static/favicon.svg")
    else:
        logger.warning("缺少前端静态资源目录: %s", static_dir)

    # 媒体文件（按目录分别挂载，避免把 chunks/logs 之类敏感目录暴露出去）
    settings_map = {
        "/media/videos": settings.storage_dir("video_dir"),
        "/media/covers": settings.storage_dir("cover_dir"),
        "/media/avatars": settings.storage_dir("avatar_dir"),
    }
    for url, directory in settings_map.items():
        directory.mkdir(parents=True, exist_ok=True)
        app.mount(url, StaticFiles(directory=str(directory)), name=url.strip("/").replace("/", "_"))

    # 管理端
    if admin_dir.exists():
        # StaticFiles 挂载点要求带尾斜杠，否则 /admin 会 404；这里补一个跳转
        @app.get("/admin", include_in_schema=False)
        def _admin_slash() -> RedirectResponse:
            return RedirectResponse(url="/admin/")

        app.mount("/admin", _FreshStaticFiles(directory=str(admin_dir), html=True), name="admin")
    else:
        logger.warning("缺少管理端目录: %s", admin_dir)

    default_site = str(settings.get("app.default_site", "web")).lower()

    # 根路径：按 default_site 决定去向（必须在挂载 "/" 之前注册）
    if default_site == "admin" and admin_dir.exists():

        @app.get("/", include_in_schema=False)
        def _root_to_admin() -> RedirectResponse:
            return RedirectResponse(url="/admin/")

    elif default_site == "none":

        @app.get("/", include_in_schema=False)
        def _root_info() -> JSONResponse:
            return JSONResponse(
                {
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "name": settings.get("app.name"),
                        "admin": "/admin/",
                        "web": "/web/",
                        "docs": "/docs",
                    },
                }
            )

    # 用户端
    if web_dir.exists():
        if default_site == "web":
            app.mount("/", _FreshStaticFiles(directory=str(web_dir), html=True), name="web")
        else:
            # 同样补一个无尾斜杠跳转
            @app.get("/web", include_in_schema=False)
            def _web_slash() -> RedirectResponse:
                return RedirectResponse(url="/web/")

            app.mount("/web", _FreshStaticFiles(directory=str(web_dir), html=True), name="web")
    else:
        logger.warning("缺少用户端目录: %s", web_dir)


def create_app() -> FastAPI:
    """构建 FastAPI 应用。"""
    settings = get_settings()
    setup_logging()

    enable_docs = bool(settings.get("dev.enable_api_docs", True))
    app = FastAPI(
        title=f"{settings.get('app.name')} API",
        version=str(settings.get("app.version", "1.0.0")),
        description=(
            "视频管理系统后端接口。\n\n"
            "- 统一响应体：`{code, msg, data}`，`code=0` 为成功\n"
            "- 认证方式：`Authorization: Bearer <token>`\n"
            "- 完整接口清单见项目 `doc/03-API接口文档.md`"
        ),
        docs_url="/docs" if enable_docs else None,
        redoc_url="/redoc" if enable_docs else None,
        openapi_url="/openapi.json" if enable_docs else None,
        lifespan=lifespan,
    )

    # CORS：前后端分离部署时按配置收紧
    origins = settings.get("app.cors_origins", ["*"]) or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True if origins != ["*"] else False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "Content-Length"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)
    app.include_router(ws_router)
    _mount_frontend(app, settings)

    return app


app = create_app()
