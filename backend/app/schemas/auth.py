"""认证相关数据模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, description="登录账号")
    password: str = Field(..., min_length=1, max_length=128, description="登录密码")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=6, max_length=64, description="新密码，至少 6 位")


class ProfileUpdateRequest(BaseModel):
    """用户自助修改资料。"""

    nickname: str | None = Field(None, max_length=64)
    avatar: str | None = Field(None, max_length=512)
    email: str | None = Field(None, max_length=128)
    phone: str | None = Field(None, max_length=32)


class LoginResponse(BaseModel):
    token: str
    token_type: str = "Bearer"
    expires_in: int
    user: dict
