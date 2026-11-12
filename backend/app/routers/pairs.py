from fastapi import APIRouter, HTTPException

from app.services import reconcile_service as svc

router = APIRouter(tags=["pairs"])


@router.get("/pairs")
def list_pairs():
    return svc.list_pairs()


@router.get("/pairs/{pair_id}/sides")
def pair_sides(pair_id: int):
    try:
        return svc.get_pair_sides(pair_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
