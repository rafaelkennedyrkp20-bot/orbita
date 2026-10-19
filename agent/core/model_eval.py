"""Comparação de modelos pelo mesmo roteiro. Velocidade não salva resposta errada.

Os casos são fixos. Quem cancela, estoura o prazo ou erra sai do ranking.
Tokens informados pelo backend têm prioridade sobre qualquer estimativa.
"""

from __future__ import annotations

CASES = [
    {
        "id": "pt-br",
        "prompt": "Responda só com a frase: O açúcar da padaria custa três reais.",
        "expect": "o açúcar da padaria custa três reais.",
    },
    {
        "id": "json",
        "prompt": 'Responda só com JSON {"ok": true, "cidade": "Recife"} sem texto em volta.',
        "expect_json": {"ok": True, "cidade": "Recife"},
    },
    {
        "id": "instrucao",
        "prompt": "Liste exatamente duas linhas, sem introdução: uma) norte duas) sul",
        "contains": ["uma) norte", "duas) sul"],
    },
    {
        "id": "documento",
        "prompt": "No texto a seguir, qual é o código do portão? Texto: O código do portão é 4312. Responda só o número.",
        "expect": "4312",
    },
    {
        "id": "codigo",
        "prompt": "Escreva só a função Python soma(a, b) que devolve a + b, sem explicação.",
        "contains": ["def soma", "return a + b"],
    },
]


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def grade(case: dict, text: str, *, cancelled: bool = False, timed_out: bool = False) -> dict:
    import json

    ok = not cancelled and not timed_out
    reason = "cancelado" if cancelled else "prazo" if timed_out else ""
    if ok and "expect" in case:
        ok = _normalize(text) == case["expect"] or case["expect"] in _normalize(text)
        reason = "" if ok else "resposta diferente"
    if ok and "contains" in case:
        low = _normalize(text)
        ok = all(piece in low for piece in case["contains"])
        reason = "" if ok else "instrução incompleta"
    if ok and "expect_json" in case:
        try:
            raw = text.strip()
            if raw.startswith("```"):
                raw = raw.strip("`")
                raw = raw.split("\n", 1)[-1]
            parsed = json.loads(raw)
            ok = parsed == case["expect_json"]
        except (json.JSONDecodeError, TypeError):
            ok = False
        reason = "" if ok else "json inválido"
    return {"id": case["id"], "ok": ok, "reason": reason, "cancelled": cancelled, "timed_out": timed_out}


def measure(case: dict, reply: dict) -> dict:
    """`reply` traz text, seconds, usage, cancelled e timed_out. Não chama rede."""
    usage = reply.get("usage") or {}
    backend = usage.get("output_tokens")
    if not isinstance(backend, int) or isinstance(backend, bool) or backend < 0:
        backend = None
    seconds = reply.get("seconds") if isinstance(reply.get("seconds"), (int, float)) else None
    graded = grade(case, reply.get("text") or "", cancelled=bool(reply.get("cancelled")),
                   timed_out=bool(reply.get("timed_out")))
    tokens_per_second = None
    if graded["ok"] and backend and seconds and seconds > 0:
        tokens_per_second = round(backend / seconds, 2)
    return {**graded, "output_tokens": backend, "seconds": seconds, "tokens_per_second": tokens_per_second,
            "cost_usd": usage.get("cost_usd")}


def rank(rows: list[dict]) -> list[dict]:
    """Só respostas corretas e completas entram. Empate prefere menos tempo, não chute rápido."""
    eligible = [row for row in rows if row.get("ok") and not row.get("cancelled") and not row.get("timed_out")]
    eligible.sort(key=lambda row: (row.get("seconds") is None, row.get("seconds") or 0))
    return eligible


def run_comparison(model_label: str, ask, *, hardware: str = "") -> list[dict]:
    """Mede os casos fixos. `ask` recebe o prompt e devolve o dict usado por `measure`.

    Não troca o modelo ativo e não executa o caso de código: a resposta é só texto.
    """
    rows = []
    label = hardware or "não informado"
    for case in CASES:
        reply = {"text": "", "usage": {}, "cancelled": False, "timed_out": False, "seconds": None}
        try:
            got = ask(case["prompt"]) or {}
            if isinstance(got, dict):
                reply.update(got)
        except TimeoutError:
            reply["timed_out"] = True
        except Exception as error:
            reply["text"] = ""
            reply["error"] = type(error).__name__
        row = measure(case, reply)
        row["model"] = model_label
        row["hardware"] = label
        row["quantization"] = "não informada"
        row["context"] = "não informado"
        rows.append(row)
    return rows
