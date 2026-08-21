import pytest

from mcp_server import qdrant_bootstrap


def configure(monkeypatch) -> None:
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("QDRANT_COLLECTION", "arduino_rag")
    monkeypatch.setenv(
        "QDRANT_SNAPSHOT_LOCATION",
        "file:///qdrant/snapshots/bootstrap/arduino_rag.snapshot",
    )
    monkeypatch.setenv("QDRANT_SNAPSHOT_CHECKSUM", "expected-checksum")


def test_existing_collection_is_not_replaced(monkeypatch) -> None:
    configure(monkeypatch)

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def collection_exists(self, collection: str) -> bool:
            assert collection == "arduino_rag"
            return True

        def recover_snapshot(self, **_kwargs) -> None:
            raise AssertionError("Existing data must not be replaced")

    monkeypatch.setattr(qdrant_bootstrap, "QdrantClient", FakeClient)
    qdrant_bootstrap.ensure_qdrant_collection(max_attempts=1)


def test_missing_collection_is_restored_from_bundled_snapshot(monkeypatch) -> None:
    configure(monkeypatch)
    checks = iter([False, True])
    recovered = {}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def collection_exists(self, _collection: str) -> bool:
            return next(checks)

        def recover_snapshot(self, **kwargs) -> None:
            recovered.update(kwargs)

    monkeypatch.setattr(qdrant_bootstrap, "QdrantClient", FakeClient)
    qdrant_bootstrap.ensure_qdrant_collection(max_attempts=1)

    assert recovered == {
        "collection_name": "arduino_rag",
        "location": "file:///qdrant/snapshots/bootstrap/arduino_rag.snapshot",
        "checksum": "expected-checksum",
        "wait": True,
    }


def test_missing_collection_requires_snapshot_configuration(monkeypatch) -> None:
    configure(monkeypatch)
    monkeypatch.delenv("QDRANT_SNAPSHOT_LOCATION")

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def collection_exists(self, _collection: str) -> bool:
            return False

    monkeypatch.setattr(qdrant_bootstrap, "QdrantClient", FakeClient)

    with pytest.raises(RuntimeError, match="was not ready"):
        qdrant_bootstrap.ensure_qdrant_collection(max_attempts=1)
