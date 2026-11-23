import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.environ.get("MONITOR_DB", ROOT / "data" / "prices.db"))


def load(path=None):
    with open(path or ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)
