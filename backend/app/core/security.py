"""安全相关：密码散列、JWT 令牌。

为降低部署依赖，这里**不引入第三方 JWT 库**，直接基于标准库实现 HS256：
- 签名算法：HMAC-SHA256
- 令牌结构：标准 JWT（header.payload.signature，base64url 无填充）
- 校验使用 :func:`hmac.compare_digest`，避免时序攻击

密码采用 PBKDF2-HMAC-SHA256，存储格式（可自描述，便于日后升级算法）::

    pbkdf2_sha256$<rounds>$<salt_hex>$<hash_hex>
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from app.core.config import get_settings
from app.core.errors import BizError, ErrorCode

# --------------------------------------------------------------------------- #
# base64url 工具
# --------------------------------------------------------------------------- #


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


# --------------------------------------------------------------------------- #
# 密码
# --------------------------------------------------------------------------- #


def hash_password(password: str, rounds: int | None = None) -> str:
    """生成密码散列。"""
    if not password:
        raise BizError(ErrorCode.PARAM_ERROR, "密码不能为空")
    rounds = rounds or int(get_settings().get("security.password_rounds", 120000))
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${dk.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """校验密码，散列格式非法时返回 False 而不是抛异常。"""
    if not password or not hashed:
        return False
    try:
        algo, rounds_str, salt_hex, hash_hex = hashed.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds_str)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def new_secret(length: int = 32) -> str:
    """生成随机密钥/盐值。"""
    return secrets.token_urlsafe(length)


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #

_ALGORITHM = "HS256"


def _sign(signing_input: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()


def create_access_token(
    payload: dict[str, Any],
    *,
    expires_minutes: int | None = None,
) -> tuple[str, int]:
    """签发访问令牌。

    :return: ``(token, expires_in_seconds)``
    """
    settings = get_settings()
    minutes = expires_minutes or int(settings.get("security.token_expire_minutes", 10080))
    secret = str(settings.get("security.secret_key", ""))
    if not secret:
        raise BizError(ErrorCode.CONFIG_ERROR, "未配置 security.secret_key")

    now = int(time.time())
    exp = now + minutes * 60
    body = {
        **payload,
        "iat": now,
        "exp": exp,
        "jti": secrets.token_hex(8),
    }
    header = {"alg": _ALGORITHM, "typ": "JWT"}
    parts = [
        b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        b64url_encode(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
    ]
    signing_input = ".".join(parts).encode("ascii")
    parts.append(b64url_encode(_sign(signing_input, secret)))
    return ".".join(parts), exp - now


def decode_access_token(token: str, *, verify_exp: bool = True) -> dict[str, Any]:
    """解析并校验令牌，失败抛 :class:`BizError`。"""
    if not token:
        raise BizError(ErrorCode.UNAUTHORIZED, "缺少登录令牌")
    secret = str(get_settings().get("security.secret_key", ""))
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError:
        raise BizError(ErrorCode.TOKEN_INVALID, "令牌格式错误") from None

    expected = _sign(f"{header_b64}.{payload_b64}".encode("ascii"), secret)
    try:
        actual = b64url_decode(signature_b64)
    except Exception:  # noqa: BLE001 - base64 解码失败统一视为非法令牌
        raise BizError(ErrorCode.TOKEN_INVALID, "令牌签名非法") from None
    if not hmac.compare_digest(expected, actual):
        raise BizError(ErrorCode.TOKEN_INVALID, "令牌签名校验失败")

    try:
        payload = json.loads(b64url_decode(payload_b64))
    except Exception:  # noqa: BLE001
        raise BizError(ErrorCode.TOKEN_INVALID, "令牌内容非法") from None

    if not isinstance(payload, dict):
        raise BizError(ErrorCode.TOKEN_INVALID, "令牌内容非法")

    if verify_exp:
        exp = int(payload.get("exp", 0))
        if exp and exp < int(time.time()):
            raise BizError(ErrorCode.TOKEN_EXPIRED, "登录已过期，请重新登录")
    return payload


__all__ = [
    "hash_password",
    "verify_password",
    "new_secret",
    "create_access_token",
    "decode_access_token",
    "b64url_encode",
    "b64url_decode",
]
