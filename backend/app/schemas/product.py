from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProductCreate(BaseModel):
    name: str
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class ProductOut(ProductCreate):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)