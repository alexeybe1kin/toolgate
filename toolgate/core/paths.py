import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TOOLGATE_DATA_DIR", ROOT))
DATA_DIR.mkdir(parents=True, exist_ok=True)

ENV_PATH = Path(os.environ.get("TOOLGATE_ENV_PATH", DATA_DIR / ".env"))
DB_PATH = DATA_DIR / "toolgate.db"
