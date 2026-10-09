"""P2-owned control-plane router. Add versioned Experience/Study APIs here."""
from fastapi import APIRouter
router = APIRouter(prefix="/v1/control", tags=["control-plane"])

@router.get("/status")
def control_status() -> dict[str, str]:
    return {"status": "scaffold", "persistence": "not_implemented"}
