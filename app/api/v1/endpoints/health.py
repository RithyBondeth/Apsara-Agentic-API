from typing import Any
from fastapi import APIRouter

router = APIRouter()


@router.get("/health", response_model=dict[str, Any])
def health_check() -> Any:
    """
    Health check endpoint.
    """
    return {"status": "ok"}
