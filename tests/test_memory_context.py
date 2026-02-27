from types import SimpleNamespace

from macgent.memory import MemoryManager


def _cfg(tmp_path):
    return SimpleNamespace(
        workspace_dir=str(tmp_path / "workspace"),
        memory_recent_days=2,
        memory_top_k=3,
    )


def test_build_context_includes_core_memory_and_skills(tmp_path):
    cfg = _cfg(tmp_path)
    mm = MemoryManager(cfg)

    (tmp_path / "workspace" / "manager").mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspace" / "manager" / "soul.md").write_text("# Manager Soul")
    (tmp_path / "workspace" / "core_memory.md").write_text("# Core Memory Contract")
    (tmp_path / "workspace" / "skills" / "x.md").write_text("# Learned Skill")

    out = mm.build_context(db=None, role="manager", task_description="")
    assert "# Manager Soul" in out
    assert "# Core Memory Contract" in out
    assert "# Learned Skill" in out


def test_recall_returns_recent_relevant_memory(tmp_path):
    cfg = _cfg(tmp_path)
    mm = MemoryManager(cfg)
    mm.remember(None, "worker", "Booking.com popup requires reject button first", category="lesson")
    mm.remember(None, "worker", "Use brave_search for research tasks", category="pattern")

    out = mm.recall(None, "worker", "booking popup", top_k=1)
    assert len(out) == 1
    assert "Booking.com popup" in out[0]["content"]
