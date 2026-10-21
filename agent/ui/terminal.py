"""Markdown ao vivo no terminal; texto simples quando Rich não está disponível."""

from __future__ import annotations


class TerminalTurn:
    def __init__(self, brain):
        self.brain = brain
        self.text = ""
        self.thinking = ""
        self.activity = []
        self.live = self.console = None

    def __enter__(self):
        try:
            from rich.console import Console
            from rich.live import Live
            from rich.spinner import Spinner

            console = Console()
            if console.is_terminal:
                self.console = console
                self.live = Live(Spinner("dots", text="Pensando…"), console=console, refresh_per_second=8)
                self.live.start()
        except ImportError:
            pass
        return self

    def events(self, kind: str, data: dict) -> None:
        if kind == "text":
            self.text += data.get("text", "")
        elif kind == "reasoning":
            self.thinking += data.get("text", "")
        elif kind == "tool_start":
            self.activity.append(data.get("name", "ferramenta"))
        if self.live:
            from rich.console import Group
            from rich.markdown import Markdown
            from rich.text import Text

            parts = []
            if self.thinking and self.brain.settings.get("show_reasoning", True):
                parts.append(Text(self.thinking, style="dim"))
            if self.activity:
                parts.append(Text("Ferramentas: " + ", ".join(self.activity[-8:]), style="cyan"))
            parts.append(Markdown(self.text or "Pensando…"))
            self.live.update(Group(*parts))
        else:
            self.brain._terminal_events(kind, data)

    def approve(self, request: dict) -> str:
        if self.live:
            self.live.stop()
        try:
            return self.brain._terminal_approve(request)
        finally:
            if self.live:
                self.live.start()

    def __exit__(self, *_error):
        if self.live:
            self.live.stop()


def run_terminal_turn(brain, text: str, *, attachments: list[str] | None = None,
                      expand_mentions: bool = True) -> str:
    from agent.core import mentions

    if expand_mentions and "@" in text:
        text = mentions.expand(text, brain.effective_workspace())
    with TerminalTurn(brain) as output:
        return brain.run_turn(text, events=output.events, approve=output.approve, attachments=attachments)
