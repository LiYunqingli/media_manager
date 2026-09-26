"""统一错误码与业务异常。

设计约定：
- HTTP 状态码用于表达传输层语义（401/403/404/500...），前端主要看响应体里的 ``code``；
- ``code == 0`` 表示成功，其余为业务错误码，前端按 ``code`` 分支处理；
- 所有业务异常统一抛 :class:`BizError`，由全局异常处理器转换为标准响应体。
"""
from __future__ import annotations

from enum import IntEnum
from typing import Any


class ErrorCode(IntEnum):
    """业务错误码。分段规则：1xxx 通用，2xxx 认证，3xxx 权限，4xxx 资源，5xxx 业务，9xxx 系统。"""

    OK = 0

    # 1xxx 通用
    PARAM_ERROR = 1001
    INVALID_REQUEST = 1002
    RATE_LIMITED = 1003

    # 2xxx 认证
    UNAUTHORIZED = 2001
    TOKEN_EXPIRED = 2002
    TOKEN_INVALID = 2003
    BAD_CREDENTIALS = 2004
    ACCOUNT_DISABLED = 2005
    ACCOUNT_EXISTS = 2006
    OLD_PASSWORD_WRONG = 2007

    # 3xxx 权限
    FORBIDDEN = 3001
    CATEGORY_FORBIDDEN = 3002
    VIDEO_FORBIDDEN = 3003

    # 4xxx 资源
    NOT_FOUND = 4001
    USER_NOT_FOUND = 4002
    CATEGORY_NOT_FOUND = 4003
    VIDEO_NOT_FOUND = 4004
    UPLOAD_NOT_FOUND = 4005
    FILE_NOT_FOUND = 4006

    # 5xxx 业务
    CATEGORY_NAME_EXISTS = 5001
    CATEGORY_NOT_EMPTY = 5002
    UPLOAD_CHUNK_INVALID = 5003
    UPLOAD_MERGE_FAILED = 5004
    UPLOAD_INCOMPLETE = 5005
    UNSUPPORTED_FILE_TYPE = 5006
    FILE_TOO_LARGE = 5007
    ALREADY_FAVORITED = 5008
    MEDIA_PROBE_FAILED = 5009

    # 9xxx 系统
    INTERNAL_ERROR = 9001
    DATABASE_ERROR = 9002
    CONFIG_ERROR = 9003


# 业务码 -> HTTP 状态码 的默认映射
_HTTP_STATUS: dict[int, int] = {
    ErrorCode.OK: 200,
    ErrorCode.PARAM_ERROR: 400,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.TOKEN_EXPIRED: 401,
    ErrorCode.TOKEN_INVALID: 401,
    ErrorCode.BAD_CREDENTIALS: 400,
    ErrorCode.ACCOUNT_DISABLED: 403,
    ErrorCode.ACCOUNT_EXISTS: 409,
    ErrorCode.OLD_PASSWORD_WRONG: 400,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.CATEGORY_FORBIDDEN: 403,
    ErrorCode.VIDEO_FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.USER_NOT_FOUND: 404,
    ErrorCode.CATEGORY_NOT_FOUND: 404,
    ErrorCode.VIDEO_NOT_FOUND: 404,
    ErrorCode.UPLOAD_NOT_FOUND: 404,
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.CATEGORY_NAME_EXISTS: 409,
    ErrorCode.CATEGORY_NOT_EMPTY: 409,
    ErrorCode.UPLOAD_CHUNK_INVALID: 400,
    ErrorCode.UPLOAD_MERGE_FAILED: 500,
    ErrorCode.UPLOAD_INCOMPLETE: 400,
    ErrorCode.UNSUPPORTED_FILE_TYPE: 415,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.ALREADY_FAVORITED: 409,
    ErrorCode.MEDIA_PROBE_FAILED: 500,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.DATABASE_ERROR: 500,
    ErrorCode.CONFIG_ERROR: 500,
}


def http_status_for(code: int) -> int:
    return _HTTP_STATUS.get(int(code), 400)


class BizError(Exception):
    """业务异常。抛出后由全局处理器统一转成标准响应体。"""

    def __init__(
        self,
        code: ErrorCode | int,
        message: str | None = None,
        *,
        http_status: int | None = None,
        data: Any = None,
    ) -> None:
        self.code = int(code)
        self.message = message or _default_message(self.code)
        self.http_status = http_status or http_status_for(self.code)
        self.data = data
        super().__init__(self.message)


_MESSAGES: dict[int, str] = {
    ErrorCode.OK: "ok",
    ErrorCode.PARAM_ERROR: "参数错误",
    ErrorCode.INVALID_REQUEST: "非法请求",
    ErrorCode.RATE_LIMITED: "请求过于频繁，请稍后再试",
    ErrorCode.UNAUTHORIZED: "请先登录",
    ErrorCode.TOKEN_EXPIRED: "登录已过期，请重新登录",
    ErrorCode.TOKEN_INVALID: "登录凭证无效",
    ErrorCode.BAD_CREDENTIALS: "用户名或密码错误",
    ErrorCode.ACCOUNT_DISABLED: "账号已被禁用",
    ErrorCode.ACCOUNT_EXISTS: "账号已存在",
    ErrorCode.OLD_PASSWORD_WRONG: "原密码错误",
    ErrorCode.FORBIDDEN: "没有操作权限",
    ErrorCode.CATEGORY_FORBIDDEN: "无权访问该分类",
    ErrorCode.VIDEO_FORBIDDEN: "无权访问该视频",
    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.USER_NOT_FOUND: "用户不存在",
    ErrorCode.CATEGORY_NOT_FOUND: "分类不存在",
    ErrorCode.VIDEO_NOT_FOUND: "视频不存在",
    ErrorCode.UPLOAD_NOT_FOUND: "上传会话不存在或已过期",
    ErrorCode.FILE_NOT_FOUND: "文件不存在",
    ErrorCode.CATEGORY_NAME_EXISTS: "分类名称已存在",
    ErrorCode.CATEGORY_NOT_EMPTY: "分类下仍有视频，无法删除",
    ErrorCode.UPLOAD_CHUNK_INVALID: "分片数据非法",
    ErrorCode.UPLOAD_MERGE_FAILED: "分片合并失败",
    ErrorCode.UPLOAD_INCOMPLETE: "分片未上传完整",
    ErrorCode.UNSUPPORTED_FILE_TYPE: "不支持的文件类型",
    ErrorCode.FILE_TOO_LARGE: "文件超过大小限制",
    ErrorCode.ALREADY_FAVORITED: "已经收藏过了",
    ErrorCode.MEDIA_PROBE_FAILED: "媒体信息解析失败",
    ErrorCode.INTERNAL_ERROR: "服务器内部错误",
    ErrorCode.DATABASE_ERROR: "数据库操作失败",
    ErrorCode.CONFIG_ERROR: "配置错误",
}


def _default_message(code: int) -> str:
    return _MESSAGES.get(code, "未知错误")
