from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.amendment_schemas import (
    AmendmentBlockerItem,
    AmendmentConfirmRequest,
    AmendmentConfirmResponse,
    AmendmentPreviewRequest,
    AmendmentPreviewResponse,
    AppliedMovementItem,
    StockImpactItem,
)
from app.core.database import get_db
from app.inventory.amendments_application import confirm_amendment_set
from app.inventory.amendments_parser import parse_preview_operations
from app.inventory.amendments_service import create_amendment_preview
from app.inventory.exceptions import AmendmentBadRequestError

router = APIRouter(prefix="/api/amendments", tags=["amendments"])


@router.post("/preview", response_model=AmendmentPreviewResponse)
def preview_amendments(
    request: AmendmentPreviewRequest,
    session: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> AmendmentPreviewResponse:
    """Предварительный просмотр набора складских исправлений без изменения состояния склада."""
    if not request.reason or not request.reason.strip():
        raise AmendmentBadRequestError(
            "Причина исправления обязательна",
            code="EMPTY_REASON",
        )

    if not request.operations:
        raise AmendmentBadRequestError(
            "Список операций не может быть пустым",
            code="EMPTY_OPERATIONS",
        )

    operations = parse_preview_operations(request.operations)
    preview_id, signature, sim_result = create_amendment_preview(
        session=session,
        reason=request.reason.strip(),
        operations=operations,
    )

    stock_impacts = [StockImpactItem(**item.to_dict()) for item in sim_result.stock_impact]
    blockers = [AmendmentBlockerItem(**b.to_dict()) for b in sim_result.blockers]

    return AmendmentPreviewResponse(
        preview_id=preview_id,
        version_signature=signature,
        can_apply=sim_result.can_apply,
        stock_impact=stock_impacts,
        affected_operations=list(sim_result.affected_operations),
        blockers=blockers,
    )


@router.post("/confirm", response_model=AmendmentConfirmResponse)
def confirm_amendments(
    request: AmendmentConfirmRequest,
    session: Annotated[Session, Depends(get_db)] = None,  # type: ignore[assignment]
) -> AmendmentConfirmResponse:
    """Атомарное подтверждение набора складских исправлений и фиксация аудита."""
    if not request.preview_id or not request.preview_id.strip():
        raise AmendmentBadRequestError(
            "Идентификатор preview_id обязателен",
            code="EMPTY_PREVIEW_ID",
        )
    if not request.version_signature or not request.version_signature.strip():
        raise AmendmentBadRequestError(
            "Подпись version_signature обязательна",
            code="EMPTY_VERSION_SIGNATURE",
        )
    if not request.reason or not request.reason.strip():
        raise AmendmentBadRequestError(
            "Причина подтверждения обязательна",
            code="EMPTY_REASON",
        )

    amendment_id, applied_moves = confirm_amendment_set(
        session=session,
        preview_id=request.preview_id.strip(),
        version_signature=request.version_signature.strip(),
        reason=request.reason.strip(),
    )

    return AmendmentConfirmResponse(
        status="applied",
        amendment_id=amendment_id,
        applied_movements=[AppliedMovementItem(**m) for m in applied_moves],
    )
