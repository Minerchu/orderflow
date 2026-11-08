from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import get_current_user
from app.constants import ROLE_WORKER
from app.core.security import create_file_token, verify_file_token
from app.db.models.order import Order, OrderAttachment
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.order import AttachmentOut
from app.services import orders as order_service
from app.services.storage import get_storage

router = APIRouter(tags=["attachments"])

ALLOWED_MIME = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


@router.post("/api/orders/{order_id}/attachments", response_model=AttachmentOut)
async def upload_attachment(
    order_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    if user.role == ROLE_WORKER:
        raise HTTPException(status_code=403, detail="worker_read_only")
    if not order_service.partner_can_access(order, user):
        raise HTTPException(status_code=403, detail="forbidden")

    data = await file.read()
    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="unsupported_file_type")
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="file_too_large")

    storage = get_storage()
    key = storage.upload(data, file.filename or "file", mime)
    att = OrderAttachment(
        order_id=order_id,
        storage_key=key,
        original_filename=file.filename,
        mime_type=mime,
        file_size=len(data),
        uploaded_by=user.id,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return AttachmentOut.model_validate(att)


@router.get("/api/orders/{order_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(
    order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    if user.role == ROLE_WORKER:
        raise HTTPException(status_code=403, detail="worker_read_only")
    if not order_service.partner_can_access(order, user):
        raise HTTPException(status_code=403, detail="forbidden")
    rows = db.execute(
        select(OrderAttachment).where(OrderAttachment.order_id == order_id)
    ).scalars().all()
    return [AttachmentOut.model_validate(r) for r in rows]


@router.delete("/api/attachments/{attachment_id}")
def delete_attachment(
    attachment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    att = db.get(OrderAttachment, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="attachment_not_found")
    if user.role == ROLE_WORKER:
        raise HTTPException(status_code=403, detail="worker_read_only")
    order = db.get(Order, att.order_id)
    # Only admin or uploader (and admin must log audit) may delete.
    if user.role != "admin" and att.uploaded_by != user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    storage = get_storage()
    storage.delete(att.storage_key)
    db.delete(att)
    if user.role == "admin":
        from app.db.models.audit import AuditLog

        db.add(AuditLog(actor_type="admin", actor_user_id=user.id,
                        action="attachment_delete", entity_type="attachment",
                        entity_id=str(attachment_id)))
    db.commit()
    return {"message": "deleted"}


@router.get("/api/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    att = db.get(OrderAttachment, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="attachment_not_found")
    if user.role == ROLE_WORKER:
        raise HTTPException(status_code=403, detail="worker_read_only")
    order = db.get(Order, att.order_id)
    if not order or not order_service.partner_can_access(order, user):
        raise HTTPException(status_code=403, detail="forbidden")
    storage = get_storage()
    if not storage.exists(att.storage_key):
        raise HTTPException(status_code=404, detail="file_missing")
    data = storage.get_bytes(att.storage_key)
    return Response(content=data, media_type=att.mime_type or "application/octet-stream",
                    headers={"Content-Disposition": f"inline; filename={att.original_filename or 'file'}"})


@router.get("/api/attachments/{attachment_id}/url")
def attachment_signed_url(
    attachment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Mint a short-lived signed URL so the browser can fetch the image directly
    (no Authorization header needed for <img> tags / window.open)."""
    att = db.get(OrderAttachment, attachment_id)
    if att is None:
        raise HTTPException(status_code=404, detail="attachment_not_found")
    if user.role == ROLE_WORKER:
        raise HTTPException(status_code=403, detail="worker_read_only")
    order = db.get(Order, att.order_id)
    if not order or not order_service.partner_can_access(order, user):
        raise HTTPException(status_code=403, detail="forbidden")
    token = create_file_token(att.storage_key)
    return {"url": f"/api/attachments/file/{att.storage_key}?token={token}", "expires_in": 900}


@router.get("/api/attachments/file/{storage_key}")
def signed_file(storage_key: str, token: str, db: Session = Depends(get_db)):
    """Short-lived signed URL access (for sharing / external retrieval)."""
    if verify_file_token(token) != storage_key:
        raise HTTPException(status_code=403, detail="invalid_token")
    att = db.execute(
        select(OrderAttachment).where(OrderAttachment.storage_key == storage_key)
    ).scalar_one_or_none()
    if att is None:
        raise HTTPException(status_code=404, detail="attachment_not_found")
    storage = get_storage()
    if not storage.exists(storage_key):
        raise HTTPException(status_code=404, detail="file_missing")
    data = storage.get_bytes(storage_key)
    return Response(content=data, media_type=att.mime_type or "application/octet-stream")
