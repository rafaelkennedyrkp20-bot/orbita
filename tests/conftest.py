"""Fixtures compartilhadas: um "brain" leve, isolado em pasta temporária."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.actions.builtin_tools import register_builtin_tools  # noqa: E402
from agent.core import routing  # noqa: E402
from agent.core.profiles import ProfileManager  # noqa: E402
from agent.core.settings import Settings  # noqa: E402
from agent.core.skills import SkillManager  # noqa: E402
from agent.core.tools import ToolRegistry  # noqa: E402
from agent.core.usage import UsageTracker  # noqa: E402


class FakeMemory:
    def __init__(self):
        self.saved = []

    def facts(self, limit=40, project=""):
        return list(self.saved)[-limit:]

    def remember_fact(self, fact, scope="global", project="", origin="user"):
        self.saved.append(fact)

    def search_facts(self, query, limit=15, project=""):
        return [f for f in self.saved if any(w in f.lower() for w in query.lower().split())]

    def get_relevant_context(self, query, max_entries=5):
        return None

    def log_interaction(self, *args, **kwargs):
        pass


class FakeMCP:
    def describe_for_prompt(self, allowed=None):
        return ""


class FakeBrain:
    """Implementa só o que AgentSession e as ferramentas usam."""

    def __init__(self, tmp_path: Path):
        self.settings = Settings(tmp_path / "settings.json")
        self.settings.set("turn_token_budget", 0, save=False)
        self.settings.set("auto_routing", False, save=False)  # testes de roteamento ligam explicitamente
        self.memory = FakeMemory()
        self.usage = UsageTracker(tmp_path / "usage.json")
        self.profiles = ProfileManager(tmp_path / "profiles")
        self.skills = SkillManager()
        self.skills.skills = {}
        self.registry = ToolRegistry()
        self.mcp = FakeMCP()
        self.local = []
        register_builtin_tools(self.registry, self)

    def route_model(self, specialty):
        # Desligado por padrão nos testes: o ambiente real (chaves, conta Grok) não deve influenciar.
        if not self.settings.get("auto_routing", False):
            return None
        return routing.best(specialty, self.settings, ("ollama", "m1"), self.local)

    def models_table(self):
        return ""

    def resolve_model(self, ref, fallback):
        if not ref:
            return fallback
        provider, _, model = ref.partition(":")
        return (provider, model) if model else fallback


@pytest.fixture
def brain(tmp_path):
    return FakeBrain(tmp_path)
