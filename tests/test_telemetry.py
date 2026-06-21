import json

from forge.telemetry.writer import TelemetryWriter


def test_versioned_bounded_and_nonblocking(tmp_path):
    path = tmp_path / "events.jsonl"
    writer = TelemetryWriter(path, max_bytes=20)
    assert writer.append({"schema_version": 1}) is None
    assert json.loads(path.read_text().splitlines()[0])["schema_version"] == 1
    assert writer.append({"schema_version": 1}) is not None
    bad = TelemetryWriter(tmp_path / "directory")
    bad.path.mkdir()
    assert "failed" in bad.append({"schema_version": 1})

