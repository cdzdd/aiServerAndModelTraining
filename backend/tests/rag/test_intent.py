import pytest

from app.modules.rag.intent import classify_intent


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("请转人工", "handoff"),
        ("我要找人工客服", "handoff"),
        ("麻烦帮我联系人工客服，谢谢", "handoff"),
        ("不要转人工，退款规则是什么", "knowledge"),
        ("我不想找人工客服", "knowledge"),
        ("如何转人工？", "knowledge"),
        ("人工客服上班时间是什么？", "knowledge"),
        ("我要投诉这次服务", "complaint"),
        ("请帮我投诉", "complaint"),
        ("投诉电话是什么", "knowledge"),
        ("我要投诉，电话是多少？", "knowledge"),
        ("如何投诉", "knowledge"),
        ("不想投诉，只想知道退款规则", "knowledge"),
        ("你好！", "other"),
        ("你好，图书馆几点开门？", "knowledge"),
        ("图书馆开放时间", "knowledge"),
    ],
)
def test_only_explicit_actions_change_intent(question, expected):
    assert classify_intent(question) == expected
