import json
from typing import Any
from subnet_validator.database.entities import DynamicConfig
from sqlalchemy.orm import Session


class DynamicConfigService:
    def __init__(self, db: Session):
        self.db = db

    def get_sync_progress(self) -> dict[str, Any]:
        value = self._get("sync_progress", "{}")
        return json.loads(value)

    def set_sync_progress(self, progress: dict[str, Any] = dict()):
        self._set("sync_progress", json.dumps(progress))

    def get_last_sync_result(self) -> dict[str, Any]:
        value = self._get("sync_last_result", "{}")
        return json.loads(value)

    def set_last_sync_result(self, result: dict[str, Any]):
        self._set("sync_last_result", json.dumps(result))

    def get_last_set_weights_time(self) -> float:
        value = self._get("last_set_weights_time", "0.0")
        return float(value)

    def set_last_set_weights_time(self, timestamp: float):
        self._set("last_set_weights_time", str(timestamp))

    def _get(self, key: str, default=None):
        row = self.db.query(DynamicConfig).filter_by(key=key).first()
        if row:
            return row.value
        return default

    def _set(self, key: str, value: str):
        row = self.db.query(DynamicConfig).filter_by(key=key).first()
        if row:
            row.value = value
        else:
            row = DynamicConfig(key=key, value=value)
            self.db.add(row)
        self.db.commit()
