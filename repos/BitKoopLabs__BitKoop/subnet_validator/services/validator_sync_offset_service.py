from datetime import UTC, datetime
from sqlalchemy.orm import Session
from subnet_validator.database.entities import ValidatorSyncOffset


class ValidatorSyncOffsetService:
    """
    Service for managing ValidatorSyncOffset records.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_last_coupon_action_date(self, hotkey: str) -> datetime | None:
        """
        Returns a dict mapping hotkey to last_coupon_action_date.
        """
        result = (
            self.db.query(ValidatorSyncOffset)
            .filter(ValidatorSyncOffset.hotkey == hotkey)
            .first()
        )
        return result.last_coupon_action_date if result else None

    def set_last_coupon_action_date(
        self, hotkey: str, value: datetime
    ) -> None:
        """
        Sets last_coupon_action_date for the given hotkey. Creates the record if it does not exist.
        """
        last_sync_time = datetime.now(UTC)
        record = (
            self.db.query(ValidatorSyncOffset)
            .filter(ValidatorSyncOffset.hotkey == hotkey)
            .first()
        )
        if record:
            record.last_coupon_action_date = value
            record.last_sync_time = last_sync_time
        else:
            record = ValidatorSyncOffset(
                hotkey=hotkey,
                last_coupon_action_date=value,
                last_sync_time=last_sync_time,
            )
            self.db.add(record)
        self.db.commit()
