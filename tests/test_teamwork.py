"""O ambiente sugere equipe quando a tarefa é grande, e só nessa hora."""

import pytest

from agent.core import teamwork as tw


@pytest.mark.parametrize("text", [
    "o que é um closure em JavaScript?",
    "corrija o erro no login",
    "faça um html bonito",
    "resuma esta conversa",
    "qual o melhor modelo para código?",
])
def test_small_requests_get_no_suggestion(text):
    assert tw.turn_hint(text, "frontier", 6) == ""


def test_user_example_with_explicit_count():
    e = tw.estimate("coloca 3 agentes pra programar um mini site simples de hacker coloca 3 agentes cada um pra "
                    "fazer uma coisa", 6)
    assert (e.size, e.helpers, e.asked) == ("grande", 3, True)


def test_big_build_with_many_parts():
    text = ("crie um site completo de loja com página inicial, catálogo de produtos, carrinho, checkout e "
            "painel administrativo")
    e = tw.estimate(text, 6)
    assert e.size == "grande" and 4 <= e.helpers <= 6
    hint = tw.turn_hint(text, "frontier", 6)
    assert "delegate_task" in hint and "Fase 1" in hint and "contract" in hint


def test_listed_parts_drive_the_count():
    text = "Monte o projeto:\n1. API de usuários\n2. tela de login\n3. painel\n4. testes\n5. documentação"
    assert tw.estimate(text, 6).helpers == 5


def test_more_helpers_than_parallel_slots_mentions_the_queue():
    text = "crie um sistema completo do zero: " + ", ".join(f"módulo {i}" for i in range(8))
    hint = tw.turn_hint(text, "standard", 2)
    assert "2 por vez" in hint and "fila" in hint


def test_small_local_models_only_team_up_when_asked():
    big = "crie um site completo de loja com página inicial, catálogo, carrinho, checkout e painel"
    assert tw.turn_hint(big, "compact", 2) == ""
    assert tw.turn_hint("divida em 3 agentes: " + big, "compact", 2) != ""


def test_parallel_limits():
    assert tw.max_parallel("frontier", "anthropic") == 6
    assert tw.max_parallel("standard", "openrouter") == 4
    assert tw.max_parallel("frontier", "ollama") == 2          # uma placa só: mais que 2 fica lento
    assert tw.max_parallel("compact", "ollama", setting=5) == 5   # a pessoa manda
