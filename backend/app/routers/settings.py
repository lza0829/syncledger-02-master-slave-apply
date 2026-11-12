from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import reconcile_service as svc

router = APIRouter(tags=["settings"])


class SettingBody(BaseModel):
    key: str
    value: str


@router.get("/settings")
def get_settings():
    return svc.list_settings()


@router.put("/settings")
def put_setting(body: SettingBody):
    try:
        return svc.update_setting(body.key, body.value)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
