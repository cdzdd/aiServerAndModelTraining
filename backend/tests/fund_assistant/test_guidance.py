import asyncio
import json

from app.modules.fund_assistant import guidance


def test_reply_reuses_reviewed_steps_and_filters_old_results_by_current_role(monkeypatch):
    async def select(_key, prompt):
        options = json.loads(prompt)["available_guides"]
        assert any(item["id"] == "admin-reclearing" for item in options)
        assert all(not item["id"].startswith("investor-") for item in options)
        return {"status": "guide", "ids": ["admin-reclearing"]}

    monkeypatch.setattr(guidance, "_classify", select)
    encoded = asyncio.run(guidance.answer("test", "ADMIN", "已用于成交的净值录错了", []))
    assert "重新清算" in guidance.view(encoded, "ADMIN")["content"]
    for role in ("INVESTOR", "OPERATOR"):
        assert guidance.view(encoded, role)["suggested_actions"] == []
        assert guidance.view(encoded, role)["sources"] == []


def test_sensitive_inputs_and_invented_routes_never_reach_the_page(monkeypatch):
    requests = []

    async def invalid(_key, prompt):
        requests.append(json.loads(prompt))
        return {"status": "guide", "ids": ["admin-reclearing"], "url": "https://example.invalid"}

    monkeypatch.setattr(guidance, "_classify", invalid)
    private = asyncio.run(
        guidance.answer("test", "INVESTOR", "我的卡号是 123456789000，它在哪看？", [])
    )
    assert "请去掉" in guidance.view(private, "INVESTOR")["content"]
    assert requests == []
    denied = asyncio.run(guidance.answer("test", "INVESTOR", "给我重清管理后台", []))
    assert guidance.view(denied, "INVESTOR")["suggested_actions"] == ["help"]
    assert "example.invalid" not in str(guidance.view(denied, "INVESTOR"))


def test_timeout_falls_back_to_reviewed_exact_match(monkeypatch):
    async def timed_out(*_args):
        raise TimeoutError

    monkeypatch.setattr(guidance, "_classify", timed_out)
    result = asyncio.run(guidance.answer("test", "INVESTOR", "第一次模拟交易？", []))
    reply = guidance.view(result, "INVESTOR")
    assert "智能识别暂不可用" in reply["content"]
    assert "account_settings" in reply["suggested_actions"]


def test_clarifying_choices_survive_follow_up_without_sending_raw_history(monkeypatch):
    choices = ["investor-default-card", "investor-change-card"]

    async def select(_key, prompt):
        values = json.loads(prompt)
        assert "历史原文" not in prompt
        if values["question"] == "2":
            assert values["previous_guide_ids"] == choices
            return {"status": "guide", "ids": [choices[1]]}
        return {"status": "clarify", "ids": choices}

    monkeypatch.setattr(guidance, "_classify", select)
    clarification = asyncio.run(guidance.answer("test", "INVESTOR", "我想换卡", []))
    assert "可以回复 1 或 2" in guidance.view(clarification, "INVESTOR")["content"]
    result = asyncio.run(
        guidance.answer(
            "test",
            "INVESTOR",
            "2",
            [
                {"role": "user", "content": "历史原文"},
                {"role": "assistant", "content": clarification},
            ],
        )
    )
    assert "申请结算换卡或解绑" in guidance.view(result, "INVESTOR")["content"]
