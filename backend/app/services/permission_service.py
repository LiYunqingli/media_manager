"""可见性 / 权限服务。

核心模型
--------
用户能看到的视频 = 「分类可见」**或**「视频被单独放行」，再减去黑名单：

1. **分类白名单**（``user_category_rule.allow = 1``）
   若用户存在任意白名单记录，则只能看到这些分类；否则默认可看全部启用分类。
2. **分类黑名单**（``allow = 0``）
   在白名单结果上再剔除。
3. **视频白名单**（``user_video_rule.allow = 1``）
   即使所属分类不可见，也强制放行该视频（例如「只给你开这一个视频」）。
4. **视频黑名单**（``allow = 0``）
   最高优先级，命中即不可见。
   典型场景：允许 user1 看分类1，但禁止分类1下的视频99。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.errors import BizError, ErrorCode
from app.repositories import category_repo, permission_repo, video_repo


@dataclass(slots=True)
class Visibility:
    """一个用户的可视范围描述，可直接展开为 video_repo 的查询参数。"""

    is_admin: bool = False
    # None 表示不受分类限制（管理员）
    category_ids: list[int] | None = None
    deny_category_ids: list[int] = field(default_factory=list)
    video_allow_ids: list[int] = field(default_factory=list)
    video_deny_ids: list[int] = field(default_factory=list)

    def as_query_kwargs(self) -> dict[str, Any]:
        """转为 ``video_repo.list_page`` 等函数的关键字参数。"""
        if self.is_admin:
            return {
                "category_ids": None,
                "deny_category_ids": [],
                "video_allow_ids": [],
                "video_deny_ids": [],
            }
        return {
            "category_ids": self.category_ids,
            "deny_category_ids": self.deny_category_ids,
            "video_allow_ids": self.video_allow_ids,
            "video_deny_ids": self.video_deny_ids,
        }

    @property
    def visible_category_ids(self) -> list[int] | None:
        return None if self.is_admin else self.category_ids


def load_rules(user_id: int) -> dict[str, list[int]]:
    """读取用户的原始规则集合（管理端展示用）。"""
    cat_rules = permission_repo.get_category_rules(user_id)
    video_rules = permission_repo.get_video_rules(user_id)
    return {
        "allow_category_ids": sorted(int(r["category_id"]) for r in cat_rules if int(r["allow"]) == 1),
        "deny_category_ids": sorted(int(r["category_id"]) for r in cat_rules if int(r["allow"]) == 0),
        "video_allow_ids": sorted(int(r["video_id"]) for r in video_rules if int(r["allow"]) == 1),
        "video_deny_ids": sorted(int(r["video_id"]) for r in video_rules if int(r["allow"]) == 0),
    }


def compute_visible_category_ids(user_id: int) -> list[int]:
    """计算用户可访问的分类 ID 集合。"""
    rules = load_rules(user_id)
    deny = set(rules["deny_category_ids"])

    if rules["allow_category_ids"]:
        base = set(rules["allow_category_ids"])
    else:
        base = {int(c["id"]) for c in category_repo.list_all(only_enabled=False)}

    return sorted(base - deny)


def get_visibility(user: dict[str, Any]) -> Visibility:
    """根据当前用户构造 Visibility。"""
    if not user:
        raise BizError(ErrorCode.UNAUTHORIZED)
    if user.get("role") == "admin":
        return Visibility(is_admin=True)

    user_id = int(user["id"])
    rules = load_rules(user_id)
    return Visibility(
        is_admin=False,
        category_ids=compute_visible_category_ids(user_id),
        deny_category_ids=rules["deny_category_ids"],
        video_allow_ids=rules["video_allow_ids"],
        video_deny_ids=rules["video_deny_ids"],
    )


def assert_category_visible(visibility: Visibility, category_id: int) -> None:
    """校验分类是否可见，不可见抛 3002。"""
    if visibility.is_admin:
        return
    if category_id in visibility.deny_category_ids:
        raise BizError(ErrorCode.CATEGORY_FORBIDDEN, "该分类不在你的可见范围内")
    if visibility.category_ids is not None and category_id not in visibility.category_ids:
        raise BizError(ErrorCode.CATEGORY_FORBIDDEN, "该分类不在你的可见范围内")


def assert_video_visible(visibility: Visibility, video: dict[str, Any]) -> None:
    """校验视频是否可见，不可见抛 3003。"""
    if visibility.is_admin:
        return
    video_id = int(video["id"])
    category_id = int(video.get("category_id") or 0)

    if video_id in visibility.video_deny_ids:
        raise BizError(ErrorCode.VIDEO_FORBIDDEN, "该视频不可访问")
    if video_id in visibility.video_allow_ids:
        return
    assert_category_visible(visibility, category_id)


def is_video_visible(visibility: Visibility, video: dict[str, Any]) -> bool:
    try:
        assert_video_visible(visibility, video)
        return True
    except BizError:
        return False


def get_visible_video(video_id: int, visibility: Visibility) -> dict[str, Any]:
    """取视频并校验可见性，统一 404 / 403 语义。"""
    video = video_repo.find_by_id(video_id)
    if not video:
        raise BizError(ErrorCode.VIDEO_NOT_FOUND)
    assert_video_visible(visibility, video)
    return video


def save_rules(user_id: int, payload: dict[str, Any]) -> dict[str, list[int]]:
    """保存用户的可见性规则（覆盖式）。"""
    allow_cats = sorted({int(x) for x in payload.get("allow_category_ids") or []})
    deny_cats = sorted({int(x) for x in payload.get("deny_category_ids") or []})
    allow_videos = sorted({int(x) for x in payload.get("video_allow_ids") or []})
    deny_videos = sorted({int(x) for x in payload.get("video_deny_ids") or []})

    # 同一分类不能既白又黑，白名单优先保留、从黑名单剔除
    deny_cats = [c for c in deny_cats if c not in allow_cats]
    # 视频黑名单优先级最高，同一视频不能同时白黑
    allow_videos = [v for v in allow_videos if v not in deny_videos]

    permission_repo.replace_rules(
        user_id,
        allow_category_ids=allow_cats,
        deny_category_ids=deny_cats,
        video_allow_ids=allow_videos,
        video_deny_ids=deny_videos,
    )
    return load_rules(user_id)


def cleanup_video_rule(video_id: int) -> None:
    """删除视频时清理相关规则。"""
    from app.db import session as db

    db.execute("DELETE FROM user_video_rule WHERE video_id = %s", (video_id,))


def cleanup_category_rule(category_id: int) -> None:
    from app.db import session as db

    db.execute("DELETE FROM user_category_rule WHERE category_id = %s", (category_id,))


def cleanup_user(user_id: int) -> None:
    """删除用户时清理其全部权限规则与播放会话。"""
    from app.db import session as db

    with db.transaction() as cur:
        cur.execute("DELETE FROM user_category_rule WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM user_video_rule WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM view_session WHERE user_id = %s", (user_id,))
