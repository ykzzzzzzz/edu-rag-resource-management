import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, model_validator

Role = Literal["student", "teacher", "admin"]
Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_.-]*$",
    ),
]
LoginUsername = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=64)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
LoginPassword = Annotated[str, StringConstraints(min_length=1, max_length=256)]
CourseName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
CourseDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _reject_explicit_null(model: BaseModel, names: tuple[str, ...]) -> None:
    for name in names:
        if name in model.model_fields_set and getattr(model, name) is None:
            raise ValueError(f"{name} 不能为空")


class LoginIn(StrictModel):
    username: LoginUsername
    password: LoginPassword


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str
    role: Role


class AdminUserOut(MeOut):
    is_active: bool
    created_at: datetime


class UserListOut(BaseModel):
    items: list[AdminUserOut]


class AdminUserCreate(StrictModel):
    username: Username
    display_name: DisplayName
    password: Password
    role: Role


class AdminUserUpdate(StrictModel):
    display_name: DisplayName | None = None
    role: Role | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _no_null_fields(self) -> "AdminUserUpdate":
        _reject_explicit_null(self, ("display_name", "role", "is_active"))
        return self


class ResetPasswordIn(StrictModel):
    new_password: Password


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


class CourseListOut(BaseModel):
    items: list[CourseOut]


class CourseCreate(StrictModel):
    name: CourseName
    description: CourseDescription | None = None


class CourseUpdate(StrictModel):
    name: CourseName | None = None
    description: CourseDescription | None = None

    @model_validator(mode="after")
    def _no_null_name(self) -> "CourseUpdate":
        # description 允许显式置为 null 以清空
        _reject_explicit_null(self, ("name",))
        return self


# ---- 资源 ----

ReviewStatus = Literal["draft", "pending", "published", "rejected", "archived"]
IndexStatus = Literal["not_indexed", "queued", "processing", "ready", "failed"]


def _no_nul(value: str) -> str:
    # PostgreSQL 文本字段不能包含 NUL，提前拒绝，避免落到数据库层变成 500
    if "\x00" in value:
        raise ValueError("不能包含 NUL 字符")
    return value


ResourceTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200), AfterValidator(_no_nul)
]
ResourceDescription = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=2000), AfterValidator(_no_nul)
]
ReviewReason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500), AfterValidator(_no_nul)]


class ResourceCreateForm(StrictModel):
    """POST /resources 的 multipart 文本字段。"""

    title: ResourceTitle
    course_id: uuid.UUID
    description: ResourceDescription | None = None


class ResourceUpdate(StrictModel):
    title: ResourceTitle | None = None
    course_id: uuid.UUID | None = None
    description: ResourceDescription | None = None

    @model_validator(mode="after")
    def _no_null_fields(self) -> "ResourceUpdate":
        # description 允许显式置为 null 以清空
        _reject_explicit_null(self, ("title", "course_id"))
        return self


class ReviewIn(StrictModel):
    action: Literal["approve", "reject"]
    reason: ReviewReason | None = None

    @model_validator(mode="after")
    def _reject_needs_reason(self) -> "ReviewIn":
        if self.action == "reject" and not self.reason:
            raise ValueError("驳回必须填写原因")
        return self


class ResourceOut(BaseModel):
    """资源响应体。不含 storage_key 和磁盘路径。

    index_error 与 review_reason 仅对资源所有者和管理员返回，其他人为 null。
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    owner_name: str
    course_id: uuid.UUID
    course_name: str
    title: str
    description: str | None
    original_filename: str
    mime_type: str
    size_bytes: int
    review_status: ReviewStatus
    index_status: IndexStatus
    index_error: str | None
    review_reason: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ResourceListOut(BaseModel):
    items: list[ResourceOut]
    total: int
    page: int
    page_size: int
