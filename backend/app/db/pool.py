"""MySQL 连接池（基于 PyMySQL 的轻量线程安全实现）。

为什么不用 SQLAlchemy：本项目全部 SQL 手写在 ``repositories`` 层，
配合 ``sql/`` 目录下的脚本，简单直接、可控性高，无需 ORM 抽象。

要点：
- 连接池用 ``queue.LifoQueue`` 管理空闲连接，借出时 ``ping(reconnect=True)`` 保活；
- 连接失效（MySQL server has gone away）自动丢弃并重建；
- ``acquire/release`` 必须成对，推荐统一使用 :func:`get_cursor` / :func:`transaction`。
"""
from __future__ import annotations

import queue
import threading
from contextlib import contextmanager
from typing import Any, Iterator

import pymysql
from pymysql.cursors import DictCursor

from app.core.config import get_settings
from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger

logger = get_logger("db")


class ConnectionPool:
    """固定容量 + 可增长的 PyMySQL 连接池。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        charset: str = "utf8mb4",
        min_size: int = 1,
        max_size: int = 10,
        wait_timeout: float = 10.0,
        connect_timeout: int = 10,
        read_timeout: int = 30,
        write_timeout: int = 30,
    ) -> None:
        self._params = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "charset": charset,
            "connect_timeout": connect_timeout,
            "read_timeout": read_timeout,
            "write_timeout": write_timeout,
            "autocommit": False,
        }
        self.min_size = max(1, min_size)
        self.max_size = max(self.min_size, max_size)
        self.wait_timeout = wait_timeout
        self._pool: queue.LifoQueue[pymysql.connections.Connection] = queue.LifoQueue(self.max_size)
        self._lock = threading.Lock()
        self._created = 0
        self._closed = False

    # ------------------------------------------------------------------ 内部
    def _new_connection(self) -> pymysql.connections.Connection:
        conn = pymysql.connect(cursorclass=DictCursor, **self._params)
        with self._lock:
            self._created += 1
        return conn

    def init(self) -> None:
        """预热 ``min_size`` 个连接。"""
        for _ in range(self.min_size):
            try:
                self._pool.put_nowait(self._new_connection())
            except Exception as exc:  # noqa: BLE001
                logger.warning("连接池预热失败（将继续按需创建）: %s", exc)
                break
        logger.info(
            "MySQL 连接池就绪 -> %s:%s/%s (min=%d, max=%d)",
            self._params["host"],
            self._params["port"],
            self._params["database"],
            self.min_size,
            self.max_size,
        )

    def acquire(self) -> pymysql.connections.Connection:
        """借出一个可用连接。"""
        if self._closed:
            raise BizError(ErrorCode.DATABASE_ERROR, "连接池已关闭")

        deadline = self.wait_timeout
        last_error: Exception | None = None

        while True:
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                with self._lock:
                    can_create = self._created < self.max_size
                    if can_create:
                        self._created += 1  # 先占位，避免并发超额
                if can_create:
                    try:
                        return self._new_connection()
                    except Exception as exc:  # noqa: BLE001
                        with self._lock:
                            self._created -= 1
                        raise BizError(ErrorCode.DATABASE_ERROR, f"数据库连接失败: {exc}") from exc
                try:
                    return self._pool.get(timeout=deadline)
                except queue.Empty:
                    raise BizError(
                        ErrorCode.DATABASE_ERROR, "数据库连接池已耗尽，请稍后重试"
                    ) from None

            # 复用前保活
            try:
                conn.ping(reconnect=True)
                return conn
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                with self._lock:
                    self._created -= 1
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                logger.warning("丢弃失效连接并重建: %s", last_error)

    def release(self, conn: pymysql.connections.Connection | None, *, broken: bool = False) -> None:
        """归还连接。broken=True 表示连接已损坏，直接销毁。"""
        if conn is None:
            return
        if broken or self._closed:
            with self._lock:
                self._created = max(0, self._created - 1)
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            if conn.open:
                # 归还前回滚未提交事务，避免脏状态污染下一个使用者
                if conn.get_autocommit() is False:
                    conn.rollback()
                self._pool.put_nowait(conn)
                return
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            self._created = max(0, self._created - 1)
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    def close_all(self) -> None:
        """关闭池内全部连接（进程退出时调用）。"""
        self._closed = True
        while True:
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                break
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._created = 0
        logger.info("连接池已关闭")

    def stats(self) -> dict[str, Any]:
        return {
            "created": self._created,
            "idle": self._pool.qsize(),
            "max": self.max_size,
        }


# --------------------------------------------------------------------------- #
# 单例
# --------------------------------------------------------------------------- #
_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    """获取全局连接池（首次调用时按配置创建并预热）。"""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        settings = get_settings()
        db = settings.section("database")
        _pool = ConnectionPool(
            host=str(db.get("host", "127.0.0.1")),
            port=int(db.get("port", 3306)),
            user=str(db.get("user", "root")),
            password=str(db.get("password", "")),
            database=str(db.get("name", "media_manager")),
            charset=str(db.get("charset", "utf8mb4")),
            min_size=int(db.get("pool_min", 1)),
            max_size=int(db.get("pool_max", 10)),
            wait_timeout=float(db.get("pool_wait_timeout", 10)),
            connect_timeout=int(db.get("connect_timeout", 10)),
            read_timeout=int(db.get("read_timeout", 30)),
            write_timeout=int(db.get("write_timeout", 30)),
        )
        _pool.init()
        return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close_all()
        _pool = None


@contextmanager
def raw_connection() -> Iterator[pymysql.connections.Connection]:
    """借出一个裸连接（自动归还）。"""
    pool = get_pool()
    conn = pool.acquire()
    broken = False
    try:
        yield conn
    except (pymysql.err.OperationalError, pymysql.err.InterfaceError) as exc:
        broken = True
        logger.error("数据库连接异常: %s", exc)
        raise BizError(ErrorCode.DATABASE_ERROR, f"数据库连接异常: {exc}") from exc
    finally:
        pool.release(conn, broken=broken)
