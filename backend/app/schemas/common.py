from __future__ import annotations

from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Message(BaseModel):
    message: str
    detail: Optional[Any] = None


class Paginated(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
