import os
from pathlib import Path

APP_NAME = "Syncledger"
DB_FILENAME = "app.db"

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SEED_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "seed"


def data_dir() -> Path:
    """Durable state dir (DB + working side fixtures). Resolved per call so
    tests can point DATA_DIR at a tmp dir."""
    return Path(os.environ.get("DATA_DIR", _DEFAULT_DATA_DIR))


def fixtures_dir() -> Path:
    """Working side storage: the fixture rows reconciliations read and
    dispositions overwrite. Lives next to the DB so ledger and side data
    share one durability story."""
    override = os.environ.get("FIXTURES_DIR")
    if override:
        return Path(override)
    return data_dir() / "fixtures"


def seed_fixtures_dir() -> Path:
    """Pristine seed fixtures bundled with the image (read-only source)."""
    return _SEED_FIXTURES_DIR
