from fastapi import APIRouter

from app.seed import reset_fixtures

router = APIRouter(tags=["fixtures"])


@router.post("/fixtures/reset")
def reset_working_fixtures():
    """Restore all working side fixtures to their pristine seeds.

    Demo affordance: makes the full-success / partial-failure disposition
    paths repeatable. Does not touch reconcile batches or the disposition
    ledger — those stay as history.
    """
    restored = reset_fixtures()
    return {"restored": restored}
