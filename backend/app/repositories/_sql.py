"""SQL 组装小工具。"""
from __future__ import annotations

from typing import Any, Iterable, Sequence


def placeholders(n: int) -> str:
    """生成 ``%s, %s, %s`` 形式的占位符串。"""
    n = max(0, int(n))
    return ",".join(["%s"] * n)


def in_clause(values: Sequence[Any], *, empty: str = "NULL") -> tuple[str, list[Any]]:
    """生成 IN 子句片段。

    :return: ``("(%s,%s)", [1, 2])``；values 为空时返回 ``("(NULL)", [])``
             这样 ``x IN (NULL)`` 恒为假，语义正确且无需在调用处特判。
    """
    if not values:
        return f"({empty})", []
    return f"({placeholders(len(values))})", list(values)


def not_in_clause(values: Sequence[Any], column: str) -> tuple[str, list[Any]]:
    """生成 ``column NOT IN (...)`` 片段。

    ⚠️ 注意：``x NOT IN (NULL)`` 在 MySQL 中结果是 NULL（即排除所有行），
    因此空集合必须退化为恒真条件 ``1=1`` 而不是 ``NOT IN (NULL)``。
    """
    if not values:
        return "1=1", []
    return f"{column} NOT IN ({placeholders(len(values))})", list(values)


def flat_params(groups: Iterable[Sequence[Any]]) -> list[Any]:
    """把多个参数序列拍平成一个列表（与 SQL 中出现顺序一致）。"""
    result: list[Any] = []
    for group in groups:
        result.extend(group)
    return result


def bool_to_int(value: Any) -> int:
    return 1 if value else 0
