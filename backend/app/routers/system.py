from fastapi import APIRouter, HTTPException

from ..system import SystemControlError, minimize_to_desktop

router = APIRouter(prefix="/system", tags=["system"])


@router.post("/minimize", status_code=204)
def minimize() -> None:
    """Only meaningful on the kiosk itself (needs a display and xdotool) —
    everywhere else this reports 503, same convention as the browser tab."""
    try:
        minimize_to_desktop()
    except SystemControlError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
