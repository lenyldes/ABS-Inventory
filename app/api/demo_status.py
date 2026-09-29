"""Читающий статус готовности демонстрационного набора."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.demo_data.inspection import DemoDataError, require_demo_as_of

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("/status")
def read_demo_status(session: Annotated[Session, Depends(get_db)]) -> dict[str, bool | date]:
    """Возвращает фактическую контрольную дату полного демонабора."""
    try:
        as_of = require_demo_as_of(session)
    except DemoDataError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"ready": True, "as_of": as_of}
