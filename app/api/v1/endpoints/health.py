from typing import Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.api import deps

router = APIRouter()


@router.get("/health", response_model=dict[str, Any])
def health_check(db: Session = Depends(deps.get_db)) -> Any:
    """
    Health check endpoint.
    """
    db_status = "ok"
    try:
        # Try to execute a simple query to verify database connection
        db.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {"status": "ok", "database": db_status}
