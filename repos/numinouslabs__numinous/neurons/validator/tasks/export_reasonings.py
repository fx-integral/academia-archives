from datetime import datetime, timezone
from uuid import UUID

from neurons.validator.db.operations import DatabaseOperations
from neurons.validator.models.numinous_client import (
    MinerReasoningSubmission,
    PostReasoningRequestBody,
)
from neurons.validator.models.reasoning import ReasoningForExport
from neurons.validator.numinous_client.client import NuminousClient
from neurons.validator.scheduler.task import AbstractTask
from neurons.validator.utils.logger.logger import NuminousLogger


class ExportReasonings(AbstractTask):
    interval: float
    batch_size: int
    db_operations: DatabaseOperations
    api_client: NuminousClient
    logger: NuminousLogger
    validator_uid: int
    validator_hotkey: str

    def __init__(
        self,
        interval_seconds: float,
        batch_size: int,
        db_operations: DatabaseOperations,
        api_client: NuminousClient,
        logger: NuminousLogger,
        validator_uid: int,
        validator_hotkey: str,
    ):
        if not isinstance(interval_seconds, float) or interval_seconds <= 0:
            raise ValueError("interval_seconds must be a positive number (float).")

        if not isinstance(db_operations, DatabaseOperations):
            raise TypeError("db_operations must be an instance of DatabaseOperations.")

        self.interval = interval_seconds
        self.batch_size = batch_size
        self.db_operations = db_operations
        self.api_client = api_client
        self.validator_uid = validator_uid
        self.validator_hotkey = validator_hotkey

        self.errors_count = 0
        self.logger = logger

    @property
    def name(self) -> str:
        return "export-reasonings"

    @property
    def interval_seconds(self) -> float:
        return self.interval

    def prepare_payload(self, reasonings: list[ReasoningForExport]) -> PostReasoningRequestBody:
        submissions = []

        for reasoning in reasonings:
            submitted_at = reasoning.created_at or datetime.now(timezone.utc)

            submission = MinerReasoningSubmission(
                event_id=reasoning.event_id,
                miner_uid=reasoning.miner_uid,
                miner_hotkey=reasoning.miner_hotkey,
                track=reasoning.track,
                validator_uid=self.validator_uid,
                validator_hotkey=self.validator_hotkey,
                run_id=UUID(reasoning.run_id),
                reasoning=reasoning.reasoning,
                submitted_at=submitted_at,
            )
            submissions.append(submission)

        return PostReasoningRequestBody(reasonings=submissions)

    async def run(self) -> None:
        unexported = await self.db_operations.get_reasonings_for_export(limit=self.batch_size)

        if not unexported:
            self.logger.debug("No unexported reasonings to export")
        else:
            self.logger.debug(
                "Found unexported reasonings to export",
                extra={"n_reasonings": len(unexported)},
            )

            payload = self.prepare_payload(reasonings=unexported)

            try:
                await self.api_client.post_reasonings(body=payload)
            except Exception:
                self.errors_count += 1
                self.logger.exception("Failed to export reasonings to backend")
                return

            run_ids = [reasoning.run_id for reasoning in unexported]
            await self.db_operations.mark_reasonings_as_exported(run_ids=run_ids)

            self.logger.debug(
                "Exported reasonings",
                extra={"n_reasonings": len(run_ids)},
            )

        self.logger.debug(
            "Export reasonings task completed",
            extra={"errors_count": self.errors_count},
        )

        self.errors_count = 0
