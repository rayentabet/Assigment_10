"""Restore the bundled Qdrant collection snapshot on a fresh deployment."""

import logging
import os
import time

from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)


def ensure_qdrant_collection(max_attempts: int = 30, retry_seconds: float = 2.0) -> None:
    """Wait for Qdrant and restore the bundled collection when it is absent."""

    url = os.environ["QDRANT_URL"]
    collection = os.environ["QDRANT_COLLECTION"]
    snapshot = os.environ.get("QDRANT_SNAPSHOT_LOCATION", "")
    checksum = os.environ.get("QDRANT_SNAPSHOT_CHECKSUM") or None
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            client = QdrantClient(url=url, check_compatibility=False)
            if client.collection_exists(collection):
                logger.info("Qdrant collection %s is ready", collection)
                return
            if not snapshot:
                raise RuntimeError(
                    f"Qdrant collection {collection!r} is missing and "
                    "QDRANT_SNAPSHOT_LOCATION is not configured."
                )
            logger.info("Restoring Qdrant collection %s from bundled snapshot", collection)
            client.recover_snapshot(
                collection_name=collection,
                location=snapshot,
                checksum=checksum,
                wait=True,
            )
            if not client.collection_exists(collection):
                raise RuntimeError(f"Qdrant did not restore collection {collection!r}.")
            logger.info("Qdrant collection %s restored", collection)
            return
        except Exception as error:
            last_error = error
            if attempt < max_attempts:
                time.sleep(retry_seconds)

    raise RuntimeError(
        f"Qdrant collection {collection!r} was not ready after {max_attempts} attempts."
    ) from last_error
