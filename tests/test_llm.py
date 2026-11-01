"""The model doorway: one setting switches backend; answers are kept and replayed; the budget
refuses before a paid call; bad JSON is asked again."""
import pytest

from forecast import llm


class Fake:
    def __init__(self, name="fake", model="m", texts=("{\"score\": 1}",), price=(0.0, 0.0)):
        self.name, self.model, self._texts, self._price, self.calls = name, model, list(texts), price, 0

    def price(self):
        return self._price

    def ask(self, prompt, system, max_tokens):
        self.calls += 1
        t = self._texts[min(self.calls - 1, len(self._texts) - 1)]
        pin, pout = self._price
        return llm.Answer(text=t, model=self.model, backend=self.name, input_tokens=10, output_tokens=5,
                          cost_usd=(10 * pin + 5 * pout) / 1e6)


def mk(tmp_path, backend, **kw):
    return llm.Port(backend, replay_path=str(tmp_path / "r.jsonl"), usage_path=str(tmp_path / "u.jsonl"), **kw)


def test_switch_is_one_setting(monkeypatch):
    monkeypatch.setenv("NEWS_LLM", "local")
    assert llm.port().spec == "ollama:qwen3.5:9b"
    monkeypatch.setenv("NEWS_LLM", "api")
    assert llm.port().spec == "anthropic:claude-haiku-5-5"
    assert llm.port("anthropic:claude-opus-5-5").spec == "anthropic:claude-opus-5-5"
    with pytest.raises(ValueError):
        llm.port("nonsense")


def test_record_then_replay_and_models_never_share_answers(tmp_path):
    a, b = Fake(model="a"), Fake(model="b")
    pa, pb = mk(tmp_path, a), mk(tmp_path, b)
    pa.complete("hello"); pa.complete("hello")
    assert a.calls == 1 and pa.complete("hello").replayed
    pb.complete("hello")
    assert b.calls == 1                                   # a different model is asked, not replayed
    with pytest.raises(llm.LLMReplayMiss):
        mk(tmp_path, a, mode="replay").complete("never asked")


def test_budget_refuses_before_paying(tmp_path):
    paid = Fake(price=(1000.0, 1000.0))                   # absurd price: one call passes $5
    p = mk(tmp_path, paid, monthly_usd=0.01)
    with pytest.raises(llm.LLMBudgetError):
        p.complete("x" * 300, max_tokens=100)
    assert paid.calls == 0


def test_json_asked_again_only_when_bad(tmp_path):
    f = Fake(texts=("not json", "{\"score\": 0.4, \"why\": \"ok\"}"))
    d, answers = mk(tmp_path, f).complete_json("score this", keys=("score", "why"))
    assert d == {"score": 0.4, "why": "ok"} and len(answers) == 2 and f.calls == 2
