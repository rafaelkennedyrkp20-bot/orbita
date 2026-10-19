"""Memória em data/, com escopo de projeto e migração idempotente."""

import json

from agent.memory.memory_manager import MemoryManager, migrate_memory


def manager(tmp_path):
    return MemoryManager(tmp_path / "daily", tmp_path / "long", tmp_path / "old-daily",
                         tmp_path / "old-long", tmp_path / "profile.json")


def test_project_facts_do_not_leak_and_globals_do(tmp_path):
    memory = manager(tmp_path)
    memory.remember_fact("gosta de café", scope="global")
    memory.remember_fact("API na porta 9", scope="project", project=str(tmp_path / "a"))
    memory.remember_fact("segredo do outro", scope="project", project=str(tmp_path / "b"))
    visible = memory.facts(project=str(tmp_path / "a"))
    assert "gosta de café" in visible
    assert "API na porta 9" in visible
    assert "segredo do outro" not in visible
    assert "segredo do outro" not in memory.search_facts("segredo", project=str(tmp_path / "a"))


def test_edit_and_delete_by_id(tmp_path):
    memory = manager(tmp_path)
    memory.remember_fact("nome antigo", scope="global", origin="user")
    item = memory.list_facts()[0]
    assert memory.update_fact(item["id"], "nome novo")
    assert memory.facts() == ["nome novo"]
    assert memory.delete_fact(item["id"])
    assert memory.facts() == []
    assert memory.delete_fact(item["id"]) is False


def test_migration_is_idempotent_and_keeps_the_source(tmp_path):
    legacy_long = tmp_path / "old-long"
    legacy_daily = tmp_path / "old-daily"
    legacy_long.mkdir()
    legacy_daily.mkdir()
    (legacy_long / "memory.json").write_text(json.dumps({"facts": [{"fact": "antigo"}]}), encoding="utf-8")
    (legacy_daily / "2026-10-01.jsonl").write_text('{"user":"oi"}\n', encoding="utf-8")
    daily, long = tmp_path / "daily", tmp_path / "long"
    migrate_memory(daily, long, legacy_daily, legacy_long)
    migrate_memory(daily, long, legacy_daily, legacy_long)
    assert json.loads((long / "memory.json").read_text(encoding="utf-8"))["facts"][0]["fact"] == "antigo"
    assert (daily / "2026-10-01.jsonl").read_text(encoding="utf-8").count("oi") == 1
    assert (legacy_long / "memory.json").is_file()
    assert (long / "backup" / "memory.json").is_file()
