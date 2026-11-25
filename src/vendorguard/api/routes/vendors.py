"""Vendor routes: the list, a vendor's history, and questions about it."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParam
from pydantic import BaseModel, Field

from vendorguard.api.deps import get_memory, get_settings
from vendorguard.config import Settings
from vendorguard.interfaces.memory import MemoryStore
from vendorguard.models.run import Answer, AssessmentSummary, VendorSummary
from vendorguard.pipeline.ask_service import answer_question
from vendorguard.pipeline.run_index import VENDOR_ID_PATTERN

router = APIRouter(prefix="/v1/vendors", tags=["vendors"])

VendorId = Annotated[
    str, PathParam(pattern=VENDOR_ID_PATTERN.pattern, description="Vendor ID, e.g. nimbara-hr.")
]


class AskRequest(BaseModel):
    """A question about one vendor's assessment history."""

    question: str = Field(min_length=1, examples=["What changed for nimbara-hr?"])


@router.get("", summary="All vendors with their number of runs and latest band")
def list_vendors(memory: Annotated[MemoryStore, Depends(get_memory)]) -> list[VendorSummary]:
    """Vendors by ID."""
    return memory.list_vendors()


@router.get("/{vendor_id}/history", summary="A vendor's assessments, newest first")
def vendor_history(
    vendor_id: VendorId, memory: Annotated[MemoryStore, Depends(get_memory)]
) -> list[AssessmentSummary]:
    """404 if nothing is stored for the vendor."""
    history = memory.list_assessments(vendor_id)
    if not history:
        raise HTTPException(status_code=404, detail="no such vendor")
    return history


@router.post("/{vendor_id}/ask", summary="Ask a question about a vendor's history")
def ask_vendor(
    vendor_id: VendorId,
    body: AskRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    memory: Annotated[MemoryStore, Depends(get_memory)],
) -> Answer:
    """The answer cites run and control IDs that exist; a model failure or a bad answer falls
    back to a fixed template (see ADR-018)."""
    return answer_question(settings, memory, vendor_id, body.question)


__all__ = ["router"]
