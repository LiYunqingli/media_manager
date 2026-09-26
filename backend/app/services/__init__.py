"""业务服务层。

分层约定：

- ``repositories`` 只写 SQL；
- ``services`` 只写业务规则，负责组合多个 repo 调用 + 事务边界；
- ``api`` 只做参数解析、鉴权、调用 service、包装响应。

服务层禁止直接抛 ``HTTPException``，一律抛 :class:`app.core.errors.BizError`。
"""
