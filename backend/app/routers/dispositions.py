from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import disposition_service as disp_svc

router = APIRouter(tags=["dispositions"])


class DispositionBody(BaseModel):
    batch_id: int
    policy: str | None = None  # omit → settings.default_policy
    note: str | None = None


@router.get("/dispositions")
def list_dispositions(limit: int = 50):
    return disp_svc.list_runs(limit=limit)


@router.get("/dispositions/{run_id}")
def get_disposition(run_id: int):
    try:
        return disp_svc.get_run(run_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/dispositions", status_code=201)
def run_disposition(body: DispositionBody):
    try:
        return disp_svc.run_disposition(body.batch_id, body.policy, body.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
