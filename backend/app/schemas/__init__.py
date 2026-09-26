"""请求 / 响应数据模型（Pydantic）。

命名约定：``XxxRequest`` 为入参，``XxxResponse`` 为出参。
出参大多直接使用 dict（数据库行），仅对需要裁剪的字段定义 Response 模型。
"""
