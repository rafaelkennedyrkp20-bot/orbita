"""Ranking de modelos: erro, cancelamento e prazo não vencem pela velocidade."""

from agent.core.model_eval import CASES, measure, rank, run_comparison


def test_fast_wrong_answer_loses_to_slow_correct_one():
    case = CASES[0]
    wrong = measure(case, {"text": "não sei", "seconds": 0.1, "usage": {"output_tokens": 20}})
    fast_cancel = measure(case, {"text": case["expect"], "seconds": 0.05, "usage": {"output_tokens": 8},
                                 "cancelled": True})
    timeout = measure(case, {"text": case["expect"], "seconds": 0.01, "timed_out": True,
                             "usage": {"output_tokens": 1}})
    right = measure(case, {"text": "O açúcar da padaria custa três reais.", "seconds": 2.5,
                           "usage": {"output_tokens": 12}})
    assert wrong["ok"] is False and fast_cancel["ok"] is False and timeout["ok"] is False
    assert right["tokens_per_second"] == round(12 / 2.5, 2)
    assert [row["seconds"] for row in rank([wrong, fast_cancel, timeout, right])] == [2.5]


def test_chunks_are_not_counted_as_backend_tokens():
    row = measure(CASES[3], {"text": "4312", "seconds": 1, "usage": {}})
    assert row["ok"] is True
    assert row["output_tokens"] is None
    assert row["tokens_per_second"] is None


def test_comparison_records_the_model_and_drops_timeouts():
    def ask(prompt):
        if "JSON" in prompt:
            raise TimeoutError("lento")
        return {"text": "resposta qualquer", "seconds": 0.2, "usage": {"output_tokens": 2}}

    rows = run_comparison("falso:modelo", ask, hardware="cpu de teste")
    assert all(row["model"] == "falso:modelo" and row["hardware"] == "cpu de teste" for row in rows)
    timed = next(row for row in rows if row["id"] == "json")
    assert timed["timed_out"] is True
    assert timed not in rank(rows)


def test_json_and_instruction_cases():
    assert measure(CASES[1], {"text": '{"ok": true, "cidade": "Recife"}', "seconds": 1,
                              "usage": {"output_tokens": 9}})["ok"]
    assert not measure(CASES[1], {"text": "Recife", "seconds": 0.2, "usage": {"output_tokens": 1}})["ok"]
    assert measure(CASES[2], {"text": "uma) norte\nduas) sul", "seconds": 1,
                              "usage": {"output_tokens": 4}})["ok"]
