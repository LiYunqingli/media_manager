"""数据访问层（Repository）。

约定：
- 只写 SQL，不写业务判断；
- 入参出参均为 dict / 标量，不定义 ORM 实体；
- 所有 SQL 使用参数化占位符；
- 表名与字段名与 ``sql/media_manager.sql`` 严格一一对应。
"""
