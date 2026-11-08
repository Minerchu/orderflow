from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.db.models.product import Product
from app.db.session import get_db
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
def list_products(db: Session = Depends(get_db), _=Depends(require_admin)):
    """Active names first; inactive ones stay so old orders still resolve."""
    rows = db.execute(
        select(Product).order_by(Product.is_active.desc(), Product.name)
    ).scalars().all()
    return [ProductOut.model_validate(r) for r in rows]


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db),
                   _=Depends(require_admin)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="product_name_required")
    if db.query(Product).filter(Product.name == name).first():
        raise HTTPException(status_code=400, detail="product_name_exists")

    p = Product(name=name, is_active=payload.is_active)
    db.add(p)
    try:
        db.commit()
    except IntegrityError as e:
        # Nearly always an unapplied migration; say so instead of a bare 500.
        db.rollback()
        logger.warning("product_create_integrity_error: %s", e)
        raise HTTPException(status_code=500, detail="product_migration_required") from None
    db.refresh(p)
    return ProductOut.model_validate(p)


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db),
                   _=Depends(require_admin)):
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="product_not_found")

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="product_name_required")
        clash = db.query(Product).filter(Product.name == name, Product.id != product_id).first()
        if clash:
            raise HTTPException(status_code=400, detail="product_name_exists")
        p.name = name

    if payload.is_active is not None:
        p.is_active = payload.is_active

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        logger.warning("product_update_integrity_error: %s", e)
        raise HTTPException(status_code=500, detail="product_migration_required") from None
    db.refresh(p)
    return ProductOut.model_validate(p)


@router.delete("/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db), _=Depends(require_admin)):
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="product_not_found")
    # Orders keep their own name snapshot, so removing a type is safe.
    db.delete(p)
    db.commit()
    return {"message": "deleted"}