from __future__ import annotations

import io

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.db.models.settlement import SettlementBatch
from app.db.session import get_db
from app.schemas.settlement import (
    SettlementCreate,
    SettlementOut,
    SettlementPreview,
    SettlementPreviewReq,
)
from app.services import settlement as settlement_service
from app.services.settlement import get_settlement_export_rows
from app.services.statistics import build_settlement_preview

router = APIRouter(prefix="/api/settlements", tags=["settlements"])


@router.post("/preview", response_model=SettlementPreview)
def preview(req: SettlementPreviewReq, db: Session = Depends(get_db),
            _=Depends(require_admin)):
    return build_settlement_preview(db, req)


@router.get("", response_model=list[SettlementOut])
def list_settlements(db: Session = Depends(get_db), _=Depends(require_admin)):
    rows = db.execute(
        select(SettlementBatch).order_by(SettlementBatch.created_at.desc())
    ).scalars().all()
    return [SettlementOut.model_validate(r) for r in rows]


@router.post("", response_model=SettlementOut, status_code=status.HTTP_201_CREATED)
def create_settlement(req: SettlementCreate, db: Session = Depends(get_db),
                      admin=Depends(require_admin)):
    try:
        batch = settlement_service.create_settlement_batch(db, req, admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SettlementOut.model_validate(batch)


@router.get("/{settlement_id}", response_model=SettlementOut)
def get_settlement(settlement_id: str, db: Session = Depends(get_db),
                   _=Depends(require_admin)):
    batch = db.execute(
        select(SettlementBatch).where(SettlementBatch.settlement_id == settlement_id)
    ).scalar_one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="settlement_not_found")
    return SettlementOut.model_validate(batch)


@router.post("/{settlement_id}/confirm", response_model=SettlementOut)
def confirm_settlement(settlement_id: str, db: Session = Depends(get_db),
                       admin=Depends(require_admin)):
    try:
        batch = settlement_service.confirm_settlement(db, settlement_id, admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SettlementOut.model_validate(batch)


@router.post("/{settlement_id}/cancel", response_model=SettlementOut)
def cancel_settlement(settlement_id: str, db: Session = Depends(get_db),
                      admin=Depends(require_admin)):
    try:
        batch = settlement_service.cancel_settlement(db, settlement_id, admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SettlementOut.model_validate(batch)


@router.get("/{settlement_id}/export")
def export_settlement(settlement_id: str, db: Session = Depends(get_db),
                      _=Depends(require_admin)):
    batch = db.execute(
        select(SettlementBatch).where(SettlementBatch.settlement_id == settlement_id)
    ).scalar_one_or_none()
    if batch is None:
        raise HTTPException(status_code=404, detail="settlement_not_found")
    summary, details, metadata = get_settlement_export_rows(batch, db)
    from openpyxl import Workbook

    wb = Workbook()
    ws1 = wb.active
    ws1.title = "Settlement Summary"
    ws1.append(["Currency", "Amount", "Quantity"])
    for r in summary:
        ws1.append([r["Currency"], r["Amount"], r["Quantity"]])

    ws2 = wb.create_sheet("Order Details")
    cols2 = ["Order ID", "Product", "Amount", "Currency", "Order Status",
             "Settlement Status", "Ledger", "Dispatcher ID", "Created At",
             "Completed At", "Accepted By", "Completed By", "Settlement ID"]
    ws2.append(cols2)
    for r in details:
        ws2.append([r[c] for c in cols2])

    ws3 = wb.create_sheet("Settlement Metadata")
    cols3 = ["Settlement ID", "Created By", "Created At", "Confirmed By",
             "Confirmed At", "Start Date", "End Date", "Number of Orders",
             "Batch Status", "Settlement Type", "Dispatcher ID"]
    ws3.append(cols3)
    for r in metadata:
        ws3.append([r[c] for c in cols3])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={batch.settlement_id}.xlsx"},
    )
