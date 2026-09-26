"""数据库访问帮助函数。

repositories 层只使用本模块提供的函数，不直接接触连接池，便于统一异常与事务处理。

约定：
- 所有 SQL 必须使用 ``%s`` 占位符传参，禁止拼接字符串（防注入）；
- 读操作使用 :func:`query_all` / :func:`query_one` / :func:`count`；
- 写操作使用 :func:`execute` / :func:`execute_return_id` / :func:`execute_many`；
- 多语句需要原子性时使用 :func:`transaction`。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Sequence

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger
from app.db.pool import get_pool

logger = get_logger("db")

Params = Sequence[Any] | dict[str, Any] | None


def _translate(exc: Exception, sql: str) -> BizError:
    """把 PyMySQL 异常翻译为业务异常，同时保留原始信息便于排查。"""
    brief = " ".join(sql.split())[:200]
    if isinstance(exc, pymysql.err.IntegrityError):
        code = getattr(exc.args[0], "real", exc.args[0]) if exc.args else "?"
        if str(code) == "1062":
            return BizError(ErrorCode.ACCOUNT_EXISTS, "数据已存在（唯一约束冲突）", data=brief)
        return BizError(ErrorCode.DATABASE_ERROR, f"数据完整性错误: {exc.args[-1]}", data=brief)
    if isinstance(exc, pymysql.err.ProgrammingError):
        return BizError(ErrorCode.DATABASE_ERROR, f"SQL 语法错误: {exc.args[-1]}", data=brief)
    return BizError(ErrorCode.DATABASE_ERROR, f"数据库操作失败: {exc}", data=brief)


@contextmanager
def get_cursor(*, commit: bool = False) -> Iterator[DictCursor]:
    """借出游标，退出时自动提交/回滚并归还连接。"""
    pool = get_pool()
    conn: Connection | None = pool.acquire()
    broken = False
    try:
        with conn.cursor() as cursor:
            try:
                yield cursor
                if commit:
                    conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    broken = True
                raise
    except BizError:
        raise
    except (pymysql.err.OperationalError, pymysql.err.InterfaceError) as exc:
        broken = True
        logger.error("数据库连接异常: %s", exc)
        raise BizError(ErrorCode.DATABASE_ERROR, f"数据库连接异常: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc, "") from exc
    finally:
        pool.release(conn, broken=broken)


@contextmanager
def transaction() -> Iterator[DictCursor]:
    """显式事务块：块内所有写操作同生共死。"""
    pool = get_pool()
    conn: Connection | None = pool.acquire()
    broken = False
    try:
        conn.begin()
        with conn.cursor() as cursor:
            try:
                yield cursor
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    broken = True
                raise
    except BizError:
        raise
    except (pymysql.err.OperationalError, pymysql.err.InterfaceError) as exc:
        broken = True
        logger.error("数据库连接异常: %s", exc)
        raise BizError(ErrorCode.DATABASE_ERROR, f"数据库连接异常: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise _translate(exc, "") from exc
    finally:
        pool.release(conn, broken=broken)


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def query_all(sql: str, params: Params = None) -> list[dict[str, Any]]:
    """查询多行。"""
    with get_cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall() or [])


def query_one(sql: str, params: Params = None) -> dict[str, Any] | None:
    """查询单行，无结果返回 None。"""
    with get_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def query_value(sql: str, params: Params = None, default: Any = None) -> Any:
    """查询单个标量值。"""
    row = query_one(sql, params)
    if not row:
        return default
    return next(iter(row.values())) if row else default


def count(sql: str, params: Params = None) -> int:
    """执行 COUNT 查询。"""
    value = query_value(sql, params, default=0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def exists(sql: str, params: Params = None) -> bool:
    return query_value(sql, params) is not None


# --------------------------------------------------------------------------- #
# 写入
# --------------------------------------------------------------------------- #
def execute(sql: str, params: Params = None) -> int:
    """执行写操作，返回受影响行数。"""
    with get_cursor(commit=True) as cur:
        cur.execute(sql, params)
        return int(cur.rowcount)


def execute_return_id(sql: str, params: Params = None) -> int:
    """执行 INSERT，返回自增主键。"""
    with get_cursor(commit=True) as cur:
        cur.execute(sql, params)
        return int(cur.lastrowid or 0)


def execute_many(sql: str, seq_params: Iterable[Sequence[Any]]) -> int:
    """批量执行，返回受影响行数。"""
    rows = list(seq_params)
    if not rows:
        return 0
    with get_cursor(commit=True) as cur:
        return int(cur.executemany(sql, rows))


def execute_multi(statements: list[tuple[str, Params]]) -> None:
    """同一事务内顺序执行多条语句。"""
    with transaction() as cur:
        for sql, params in statements:
            cur.execute(sql, params)


# --------------------------------------------------------------------------- #
# 分页工具
# --------------------------------------------------------------------------- #
def build_page(page: int, page_size: int, max_size: int = 100) -> tuple[int, int]:
    """规整分页参数，返回 ``(page, page_size, offset)`` 中的前两项 + offset。"""
    page = max(1, int(page or 1))
    page_size = int(page_size or 20)
    page_size = max(1, min(page_size, max_size))
    return page, page_size
