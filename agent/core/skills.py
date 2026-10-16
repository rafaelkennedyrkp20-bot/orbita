"""
skills.py — Skills no padrão aberto Agent Skills (SKILL.md) + plugins.

Uma skill é uma pasta com `SKILL.md` (frontmatter YAML com `name` e `description`
seguido de instruções em Markdown). Carregamento progressivo: só nome e descrição
entram no prompt; o corpo é lido quando a IA chama `use_skill`.

Pastas lidas (as mesmas usadas por Claude Code, Codex e outros agentes):
    <projeto>/skills, <projeto>/plugins/*/skills,
    ~/.claude/skills, ~/.agents/skills, ~/.codex/skills
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from agent.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

HOME = Path.home()
PROJECT_SKILLS = PROJECT_ROOT / "skills"
PLUGINS_DIR = PROJECT_ROOT / "plugins"
USER_SKILL_DIRS = [HOME / ".claude" / "skills", HOME / ".agents" / "skills", HOME / ".codex" / "skills"]

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    path: Path          # SKILL.md
    origin: str         # projeto | plugin:<nome> | usuário

    @property
    def folder(self) -> Path:
        return self.path.parent


def parse_skill_file(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    try:
        import yaml

        meta = yaml.safe_load(match.group(1)) or {}
    except Exception:
        meta = {}
        for line in match.group(1).splitlines():
            if ":" in line and not line.startswith(" "):
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip().strip('"')
    return (meta if isinstance(meta, dict) else {}), match.group(2)


class SkillManager:

    def __init__(self, extra_dirs: list[Path] | None = None):
        self.extra_dirs = extra_dirs or []
        self.skills: dict[str, Skill] = {}
        self.reload()

    def _sources(self) -> list[tuple[Path, str]]:
        sources = [(PROJECT_SKILLS, "projeto")]
        if PLUGINS_DIR.is_dir():
            for plugin in sorted(PLUGINS_DIR.iterdir()):
                if plugin.is_dir():
                    sources.append((plugin / "skills", f"plugin:{plugin.name}"))
        sources += [(d, "usuário") for d in USER_SKILL_DIRS + self.extra_dirs]
        return sources

    def reload(self) -> None:
        found: dict[str, Skill] = {}
        for base, origin in self._sources():
            if not base.is_dir():
                continue
            for skill_file in sorted(base.glob("*/SKILL.md")):
                try:
                    meta, _ = parse_skill_file(skill_file)
                except OSError as error:
                    logger.warning("Skill ilegível %s: %s", skill_file, error)
                    continue
                name = str(meta.get("name") or skill_file.parent.name).strip()
                description = " ".join(str(meta.get("description") or "").split())
                if not description or name in found:  # a primeira origem vence (projeto > plugin > usuário)
                    continue
                found[name] = Skill(name, description[:1024], skill_file, origin)
        self.skills = found
        logger.info("Skills carregadas: %d", len(found))

    def index_text(self, max_chars: int = 6000) -> str:
        lines, used = [], 0
        for skill in sorted(self.skills.values(), key=lambda s: s.name):
            line = f"- {skill.name}: {skill.description[:300]}"
            used += len(line)
            if used > max_chars:
                lines.append(f"- ... e mais {len(self.skills) - len(lines)} skills (use_skill com o nome exato)")
                break
            lines.append(line)
        return "\n".join(lines)

    def load(self, name: str, file: str | None = None) -> str:
        skill = self.skills.get(name) or next(
            (s for s in self.skills.values() if s.name.lower() == name.lower()), None)
        if skill is None:
            return f"Skill '{name}' não existe. Disponíveis: {', '.join(sorted(self.skills)) or 'nenhuma'}"
        if file:
            target = (skill.folder / file).resolve()
            if skill.folder.resolve() not in target.parents or not target.is_file():
                return f"Arquivo '{file}' não encontrado dentro da skill {skill.name}."
            return target.read_text(encoding="utf-8", errors="replace")[:30000]
        _, body = parse_skill_file(skill.path)
        extras = [str(p.relative_to(skill.folder)) for p in skill.folder.rglob("*")
                  if p.is_file() and p.name != "SKILL.md"][:40]
        listing = f"\n\nArquivos da skill (leia com use_skill name='{skill.name}' file='...'): {', '.join(extras)}" if extras else ""
        return f"# Skill: {skill.name}\nPasta: {skill.folder}\n\n{body.strip()}{listing}"

    def plugin_mcp_configs(self) -> list[tuple[str, Path]]:
        """Arquivos `.mcp.json` fornecidos por plugins."""
        if not PLUGINS_DIR.is_dir():
            return []
        return [(p.name, p / ".mcp.json") for p in sorted(PLUGINS_DIR.iterdir()) if (p / ".mcp.json").is_file()]
