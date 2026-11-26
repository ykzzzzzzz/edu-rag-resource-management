from fastapi import APIRouter, Request

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/mode")
def get_mode(request: Request) -> dict[str, str]:
    return {"qa_mode": request.app.state.settings.qa_mode}
