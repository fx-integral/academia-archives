from __future__ import annotations

import os
import time
from datetime import datetime
from types import TracebackType
from typing import Any, Dict, List, NoReturn, Optional, Sequence, Set, Type

import bittensor as bt
import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from ..scoring.models import ValidationRecord
from .fallback import filter_usable_records

load_dotenv()

DEFAULT_VALIDATION_ENDPOINT = (
    "https://api.wahoopredict.com/api/v2/event/bittensor/statistics/v2"
)

RETRY_STATUS_CODES = {429}
RETRY_STATUS_CODES.update(range(500, 600))

WAHOO_API_MAX_RETRIES = 2
WAHOO_API_BACKOFF_SECONDS = 1.0

EVENT_ID_MAX_RETRIES = 0

SET_WEIGHTS_MAX_RETRIES = 1


class ValidationAPIError(RuntimeError):
    pass


def _parse_iso8601(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO 8601 datetime: {value}") from exc


class ValidationAPIClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = 30.0,
        max_retries: int = WAHOO_API_MAX_RETRIES,
        backoff_seconds: float = WAHOO_API_BACKOFF_SECONDS,
        session: Optional[httpx.Client] = None,
    ):
        resolved_url = base_url or os.getenv(
            "WAHOO_VALIDATION_ENDPOINT", DEFAULT_VALIDATION_ENDPOINT
        )
        self.base_url = resolved_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._session = session or httpx.Client(timeout=self.timeout)
        self._owns_session = session is None

    def __enter__(self) -> "ValidationAPIClient":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_session:
            self._session.close()

    def fetch_validation_data(
        self,
        *,
        hotkeys: Sequence[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[ValidationRecord]:
        valid_hotkeys = self._normalize_hotkeys(hotkeys)
        params: Dict[str, str] = {"hotkeys": ",".join(valid_hotkeys)}

        start_dt: Optional[datetime] = None
        end_dt: Optional[datetime] = None
        if start_date:
            start_dt = _parse_iso8601(start_date)
            params["start_date"] = start_date
        if end_date:
            end_dt = _parse_iso8601(end_date)
            params["end_date"] = end_date
        if start_dt and end_dt and start_dt >= end_dt:
            raise ValueError("start_date must be earlier than end_date")

        response = self._request_with_retries(params)
        payload = self._extract_payload(response)
        records: List[ValidationRecord] = []
        returned_hotkeys: Set[str] = set()

        # Process records returned by the API
        for item in payload:
            try:
                record = ValidationRecord.model_validate(item)
                records.append(record)
                returned_hotkeys.add(record.hotkey)
            except ValidationError as exc:
                raise ValidationAPIError(f"Invalid validation record: {exc}") from exc

        # Create records for hotkeys that weren't returned by the API
        # This ensures all registered hotkeys have records, even if they have no data
        missing_hotkeys = set(valid_hotkeys) - returned_hotkeys
        for hotkey in missing_hotkeys:
            record = ValidationRecord(hotkey=hotkey)
            records.append(record)

        return records

    def _normalize_hotkeys(self, hotkeys: Sequence[str]) -> List[str]:
        if not hotkeys:
            raise ValueError("hotkeys list cannot be empty")
        deduped: List[str] = []
        seen: Set[str] = set()
        for hotkey in hotkeys:
            hk = (hotkey or "").strip()
            if not hk:
                continue
            if hk not in seen:
                seen.add(hk)
                deduped.append(hk)
        if not deduped:
            raise ValueError("hotkeys list cannot be empty")
        return deduped

    def _request_with_retries(self, params: Dict[str, str]) -> httpx.Response:
        url = self.base_url
        attempt = 0
        max_attempts = self.max_retries + 1

        while attempt < max_attempts:
            attempt += 1

            if attempt > 1:
                bt.logging.info(
                    f"ValidationAPI retry attempt {attempt}/{max_attempts} "
                    f"(max_retries={self.max_retries})"
                )

            try:
                response = self._session.get(url, params=params)
            except httpx.TimeoutException as exc:
                bt.logging.error(
                    f"ValidationAPI request timed out after {self.timeout}s "
                    f"(attempt {attempt}/{max_attempts}): {exc}"
                )
                raise ValidationAPIError(
                    f"Validation API request timed out after {self.timeout}s"
                ) from exc
            except httpx.HTTPError as exc:
                bt.logging.warning(
                    f"ValidationAPI request failed "
                    f"(attempt {attempt}/{max_attempts}): {exc}"
                )
                if attempt >= max_attempts:
                    bt.logging.error(
                        f"ValidationAPI exhausted all {max_attempts} attempts"
                    )
                    raise ValidationAPIError(
                        "Failed to reach validation endpoint after all retries"
                    ) from exc
                self._sleep_backoff(attempt)
                continue

            if response.status_code == 200:
                if attempt > 1:
                    bt.logging.info(
                        f"ValidationAPI request succeeded on attempt "
                        f"{attempt}/{max_attempts}"
                    )
                return response

            if response.status_code in RETRY_STATUS_CODES and attempt < max_attempts:
                bt.logging.warning(
                    f"ValidationAPI transient error (status={response.status_code}, "
                    f"attempt {attempt}/{max_attempts}), retrying..."
                )
                self._sleep_backoff(attempt)
                continue

            self._log_and_raise(response)
        raise ValidationAPIError("Exhausted retries for validation endpoint")

    def _sleep_backoff(self, attempt: int) -> None:
        delay = min(30.0, self.backoff_seconds * (2 ** (attempt - 1)))
        time.sleep(delay)

    @staticmethod
    def _extract_payload(response: httpx.Response) -> List[Dict[str, Any]]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ValidationAPIError(
                "Validation endpoint returned invalid JSON"
            ) from exc

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "data" in data and isinstance(data["data"], list):
                return list(data["data"])
            return []
        raise ValidationAPIError("Unexpected response format from validation endpoint")

    def _log_and_raise(self, response: httpx.Response) -> NoReturn:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        bt.logging.error(
            f"ValidationAPI request failed with status "
            f"{response.status_code}: {payload}"
        )
        raise ValidationAPIError(
            f"Validation API request failed with status {response.status_code}"
        )


def get_active_event_id(
    api_base_url: Optional[str] = None,
    *,
    timeout: float = 10.0,
    default_event_id: str = "wahoo_test_event",
) -> str:
    if api_base_url:
        base_url = api_base_url.rstrip("/")
    else:
        base_url = os.getenv("WAHOO_API_URL", "https://api.wahoopredict.com").rstrip(
            "/"
        )

    events_url = f"{base_url}/api/v2/event/events-list"

    try:
        import json

        request_body = {
            "page": 1,
            "limit": 20,
            "sort": {"sortBy": "estimatedEnd", "sortOrder": "desc"},
            "filter": {"status": ["LIVE"]},
        }

        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                events_url,
                headers={"Content-Type": "application/json"},
                content=json.dumps(request_body),
            )
            response.raise_for_status()

            data = response.json()

            if isinstance(data, list) and len(data) > 0:
                first_event = data[0]
                event_id = (
                    first_event.get("id")
                    or first_event.get("event_id")
                    or first_event.get("_id")
                )
                if event_id:
                    bt.logging.info(f"Retrieved active event_id: {event_id}")
                    return str(event_id)

            if isinstance(data, dict):
                if (
                    "data" in data
                    and isinstance(data["data"], list)
                    and len(data["data"]) > 0
                ):
                    first_event = data["data"][0]
                    event_id = (
                        first_event.get("id")
                        or first_event.get("event_id")
                        or first_event.get("_id")
                    )
                    if event_id:
                        bt.logging.info(f"Retrieved active event_id: {event_id}")
                        return str(event_id)

                event_id = (
                    data.get("active_event_id")
                    or data.get("event_id")
                    or data.get("id")
                    or data.get("event")
                )
                if event_id:
                    bt.logging.info(f"Retrieved active event_id: {event_id}")
                    return str(event_id)

            bt.logging.warning(
                f"Could not extract event_id from response: {data}. "
                f"Using default: {default_event_id}"
            )
            return default_event_id

    except httpx.TimeoutException as exc:
        bt.logging.warning(
            f"Events API request timed out after {timeout}s: {exc}. "
            f"Falling back to default event_id: {default_event_id}"
        )
        return default_event_id
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        bt.logging.warning(
            f"Failed to get active event_id from API: {exc}. "
            f"Falling back to default event_id: {default_event_id}"
        )
        return default_event_id


class ValidatorDBInterface:
    def cache_validation_data(self, hotkey: str, data_dict: Dict[str, Any]) -> None:
        raise NotImplementedError

    def get_cached_validation_data(
        self, hotkeys: Sequence[str], max_age_days: int = 7
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def delete_cached_validation_data(self, hotkeys: Sequence[str]) -> None:
        """
        Delete cached validation data for given hotkeys.

        Args:
            hotkeys: List of hotkeys to delete from cache

        Note:
            This method is optional. If not implemented, invalid cache entries
            will be skipped but not deleted.
        """
        raise NotImplementedError

    def cleanup_old_cache(self, max_age_days: int = 7) -> int:
        """
        Delete cache entries older than max_age_days and run VACUUM.

        Args:
            max_age_days: Delete entries older than this many days (default: 7)

        Returns:
            Number of entries deleted

        Note:
            Should run VACUUM after deletion to reclaim disk space.
        """
        raise NotImplementedError

    def add_scoring_run(
        self, scores: Dict[str, float], reason: str = "ema_update"
    ) -> None:
        """
        Save EMA scores to DB.

        Args:
            scores: Dictionary of hotkey -> score
            reason: Reason for the update (default: "ema_update")
        """
        raise NotImplementedError

    def get_latest_scores(self) -> Dict[str, float]:
        """
        Retrieve the most recent score for every hotkey.

        Returns:
            Dictionary of hotkey -> score
        """
        raise NotImplementedError

    def remove_unregistered_miners(self, registered_hotkeys: Sequence[str]) -> int:
        """
        Remove all miners from the database that are not in the registered_hotkeys list.
        This deletes entries from miners, performance_snapshots, and scoring_runs tables.

        Args:
            registered_hotkeys: List of hotkeys that are currently registered

        Returns:
            Number of miners removed
        """
        raise NotImplementedError


def get_wahoo_validation_data(
    hotkeys: Sequence[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    *,
    max_per_batch: int = 64,
    batch_timeout: float = 30.0,
    api_base_url: Optional[str] = None,
    validator_db: Optional[ValidatorDBInterface] = None,
    client: Optional[ValidationAPIClient] = None,
) -> List[ValidationRecord]:
    if not hotkeys:
        return []

    valid_hotkeys = list(dict.fromkeys(str(hk).strip() for hk in hotkeys if hk))
    if not valid_hotkeys:
        return []

    endpoint = (
        api_base_url.rstrip("/")
        if api_base_url
        else os.getenv("WAHOO_VALIDATION_ENDPOINT", DEFAULT_VALIDATION_ENDPOINT)
    )

    if client is None:
        client = ValidationAPIClient(base_url=endpoint, timeout=batch_timeout)
    else:
        client.base_url = endpoint
        client.timeout = batch_timeout

    batches = [
        valid_hotkeys[i : i + max_per_batch]
        for i in range(0, len(valid_hotkeys), max_per_batch)
    ]

    bt.logging.info(
        f"Processing {len(valid_hotkeys)} hotkeys in {len(batches)} batches "
        f"(max {max_per_batch} per batch, {batch_timeout}s timeout)"
    )

    all_records: List[ValidationRecord] = []
    successful_batches = 0
    failed_batches = 0

    for batch_num, batch in enumerate(batches, 1):
        try:
            records = client.fetch_validation_data(
                hotkeys=batch,
                start_date=start_date,
                end_date=end_date,
            )

            if validator_db is not None:
                try:
                    for record in records:
                        validator_db.cache_validation_data(
                            hotkey=record.hotkey, data_dict=record.model_dump()
                        )
                except Exception as e:
                    bt.logging.warning(f"Failed to cache batch {batch_num}: {e}")

            all_records.extend(records)
            successful_batches += 1
            bt.logging.debug(
                f"Batch {batch_num}/{len(batches)}: {len(records)} records"
            )

        except ValidationAPIError as e:
            bt.logging.warning(
                f"Batch {batch_num}/{len(batches)} failed: {e}. "
                "Attempting cache fallback..."
            )

            if validator_db is not None:
                try:
                    cached_data = validator_db.get_cached_validation_data(
                        hotkeys=batch, max_age_days=7
                    )
                    if cached_data:
                        cached_records = []
                        invalid_hotkeys = []

                        for data_dict in cached_data:
                            try:
                                record = ValidationRecord.model_validate(data_dict)
                                cached_records.append(record)
                            except Exception as validation_error:
                                hotkey = data_dict.get("hotkey", "unknown")
                                invalid_hotkeys.append(hotkey)
                                bt.logging.debug(
                                    f"Invalid cached data for hotkey {hotkey}: "
                                    f"{validation_error}. Will be deleted from cache."
                                )
                                continue

                        if invalid_hotkeys and hasattr(
                            validator_db, "delete_cached_validation_data"
                        ):
                            try:
                                validator_db.delete_cached_validation_data(
                                    hotkeys=invalid_hotkeys
                                )
                                bt.logging.info(
                                    f"Deleted {len(invalid_hotkeys)} "
                                    f"invalid cache entry/entries"
                                )
                            except Exception as delete_error:
                                bt.logging.warning(
                                    f"Failed to delete invalid cache entries: "
                                    f"{delete_error}"
                                )

                        total_requested = len(batch)
                        total_cached = len(cached_data)
                        valid_cached = len(cached_records)
                        invalid_cached = len(invalid_hotkeys)
                        missing_from_cache = total_requested - total_cached

                        if cached_records:
                            bt.logging.info(
                                f"Cache fallback used for batch {batch_num}: "
                                f"{valid_cached} valid cached records, "
                                f"{invalid_cached} invalid (deleted), "
                                f"{missing_from_cache} not in cache "
                                f"(requested {total_requested} hotkeys)"
                            )
                            all_records.extend(cached_records)
                            successful_batches += 1
                            continue
                        else:
                            bt.logging.warning(
                                f"Cache fallback for batch {batch_num}: "
                                f"All {total_cached} cached entries were invalid "
                                f"or missing. Requested {total_requested} hotkeys."
                            )
                    else:
                        bt.logging.warning(
                            f"Cache fallback for batch {batch_num}: "
                            f"No cached data found for {len(batch)} hotkeys"
                        )
                except Exception as cache_error:
                    bt.logging.warning(
                        f"Cache fallback failed for batch {batch_num}: {cache_error}"
                    )

            bt.logging.warning(
                f"Batch {batch_num}/{len(batches)} skipped (no cache available)"
            )
            failed_batches += 1

        except Exception as e:
            bt.logging.error(f"Batch {batch_num}/{len(batches)} error: {e}")
            failed_batches += 1

    bt.logging.info(
        f"Batching complete: {successful_batches} successful, "
        f"{failed_batches} failed, {len(all_records)} total records"
    )

    usable_records = filter_usable_records(all_records)
    if len(usable_records) < len(all_records):
        excluded = len(all_records) - len(usable_records)
        bt.logging.info(
            f"Filtered {excluded} record(s) with empty metrics. "
            f"Returning {len(usable_records)} usable records."
        )

    return usable_records
