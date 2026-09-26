"""用户与权限相关数据模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class UserCreateRequest(BaseModel):
    """管理端创建用户（系统不开放注册，账号只能由管理端创建）。"""

    username: str = Field(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(..., min_length=6, max_length=64)
    nickname: str = Field("", max_length=64)
    role: str = Field("user", pattern=r"^(admin|user)$")
    status: int = Field(1, ge=0, le=1)
    email: str = Field("", max_length=128)
    phone: str = Field("", max_length=32)
    remark: str = Field("", max_length=255)
    # 分类白名单：非空时该用户【只能】看到这些分类
    allow_category_ids: list[int] = Field(default_factory=list)


class UserUpdateRequest(BaseModel):
    """管理端更新用户基础信息（不含权限，权限走 /permissions 接口）。"""

    nickname: str | None = Field(None, max_length=64)
    role: str | None = Field(None, pattern=r"^(admin|user)$")
    status: int | None = Field(None, ge=0, le=1)
    email: str | None = Field(None, max_length=128)
    phone: str | None = Field(None, max_length=32)
    remark: str | None = Field(None, max_length=255)
    avatar: str | None = Field(None, max_length=512)


class AdminResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=64)


class UserRulesRequest(BaseModel):
    """用户可见性规则（整体覆盖式保存）。

    三张表的语义：

    - ``allow_category_ids``：分类白名单。**非空**时该用户只能看这些分类；
      为空表示「不受白名单限制」（默认可看全部启用分类）。
    - ``deny_category_ids``：分类黑名单，优先级高于白名单。
    - ``video_deny_ids``：视频黑名单，例如「允许看分类1，但禁止分类1下的视频1」。
    - ``video_allow_ids``：视频强制放行（即使所属分类不可见）。
    """

    allow_category_ids: list[int] = Field(default_factory=list)
    deny_category_ids: list[int] = Field(default_factory=list)
    video_allow_ids: list[int] = Field(default_factory=list)
    video_deny_ids: list[int] = Field(default_factory=list)


class UserQuery(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    keyword: str = Field("", max_length=64)
    role: str = Field("", pattern=r"^(|admin|user)$")
    status: str = Field("", pattern=r"^(|0|1)$")
