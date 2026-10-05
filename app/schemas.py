from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models import ShareRole, Visibility


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    is_admin: bool
    model_config = {"from_attributes": True}


class ListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=220)
    description: str = ""
    visibility: Visibility = Visibility.private
    custom_metadata: dict[str, Any] = Field(default_factory=dict)


class ListUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=220)
    description: str | None = None
    visibility: Visibility | None = None
    default_sort: dict[str, Any] | None = None
    custom_metadata: dict[str, Any] | None = None
    archived: bool | None = None


class ListOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    owner_id: str
    visibility: Visibility
    default_sort: dict[str, Any]
    custom_metadata: dict[str, Any]
    archived: bool
    model_config = {"from_attributes": True}


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    description: str = ""
    quantity: float = Field(default=1, ge=0)
    unit: str = Field(default="each", max_length=40)
    category: str | None = Field(default=None, max_length=120)
    tags: list[str] = Field(default_factory=list)
    storage_location: str | None = Field(default=None, max_length=240)
    usage_context: str | None = Field(default=None, max_length=240)
    is_required: bool = True
    notes: str = ""
    position: int | None = Field(default=None, ge=0)
    referenced_list_id: str | None = None
    identity_key: str | None = Field(default=None, max_length=160)
    conditional_requirements: dict[str, Any] = Field(default_factory=dict)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)
    dependency_ids: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, tags: list[str]) -> list[str]:
        return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


class ItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    storage_location: str | None = None
    usage_context: str | None = None
    is_required: bool | None = None
    notes: str | None = None
    position: int | None = Field(default=None, ge=0)
    referenced_list_id: str | None = None
    identity_key: str | None = None
    conditional_requirements: dict[str, Any] | None = None
    custom_metadata: dict[str, Any] | None = None
    dependency_ids: list[str] | None = None


class ItemOut(BaseModel):
    id: str
    list_id: str
    name: str
    description: str
    quantity: float
    unit: str
    category: str | None
    tags: list[str]
    storage_location: str | None
    usage_context: str | None
    is_required: bool
    notes: str
    position: int
    referenced_list_id: str | None
    identity_key: str | None
    conditional_requirements: dict[str, Any]
    custom_metadata: dict[str, Any]
    model_config = {"from_attributes": True}


class ShareCreate(BaseModel):
    user_id: str
    role: ShareRole


class ResolutionOptions(BaseModel):
    merge_duplicates: bool = True
    combine_quantities: bool = True
    expand_dependencies: bool = False
    include_optional: bool = True
    group_by_category: bool = False
    sort_by: Literal["position", "name", "category", "location"] = "position"
    sort_direction: Literal["asc", "desc"] = "asc"
    preserve_source: bool = True
    conflict_strategy: Literal["first", "last", "error"] = "first"
    quantity_multiplier: float = Field(default=1.0, ge=0)
    round_quantity: int | None = Field(default=None, ge=0, le=8)


class ExportProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    format: Literal["json", "csv"]
    options: ResolutionOptions = Field(default_factory=ResolutionOptions)
