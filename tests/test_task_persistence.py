from forge.persistence import TaskStore
from forge.service import ForgeService


def test_state_survives_service_restart(tmp_path, repo):
    root = tmp_path / "runtime"
    first = ForgeService(root, clock=lambda: 1, id_factory=lambda seed: "stable")
    task_id = first.forge_start_task("task", str(repo))["task_id"]
    first.forge_finish_task(task_id, False, "failed")
    second = ForgeService(root)
    assert second.tasks.get(task_id).state == "failed"


def test_corrupt_records_do_not_hide_valid_tasks(tmp_path, repo):
    root = tmp_path / "runtime"
    service = ForgeService(root, clock=lambda: 1, id_factory=lambda seed: "stable")
    task_id = service.forge_start_task("task", str(repo))["task_id"]
    path = root / "tasks.jsonl"
    path.write_text("{bad json}\n" + path.read_text(), encoding="utf-8")
    store = TaskStore(path)
    assert store.get(task_id) is not None
    assert store.warnings


def test_compaction_preserves_latest_snapshot(tmp_path, repo):
    root = tmp_path / "runtime"
    service = ForgeService(root, clock=lambda: 1, id_factory=lambda seed: "stable")
    task_id = service.forge_start_task("task", str(repo))["task_id"]
    service.forge_finish_task(task_id, False, "failed")
    service.tasks.compact()
    assert len((root / "tasks.jsonl").read_text().splitlines()) == 1
    assert TaskStore(root / "tasks.jsonl").get(task_id).state == "failed"

