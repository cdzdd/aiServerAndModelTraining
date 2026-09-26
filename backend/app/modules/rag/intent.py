"""Conservative local routing; knowledge questions remain in retrieval."""

import re
from typing import Literal

Intent = Literal["knowledge", "complaint", "handoff", "other"]


def classify_intent(question: str) -> Intent:
    text = question.strip().lower()
    # A request for the process, contact details or opening hours is still knowledge.
    if re.search(r"如何|怎么|怎样|电话|流程|渠道|方式|上班|时间|哪里|在哪", text):
        return "knowledge"
    clauses = re.split(r"[，,。.!！?？;；]", text)
    for clause in clauses:
        clause = clause.strip()
        if re.search(r"不|别|无需|不用", clause):
            continue
        if re.fullmatch(
            r"(?:请|麻烦|帮我|给我|我想|我要|我需要|请帮我|麻烦帮我)*"
            r"(?:转(?:接)?人工(?:客服)?|找人工客服|联系人工客服|人工客服)(?:一下|吧|谢谢)*",
            clause,
        ):
            return "handoff"
    for clause in clauses:
        if re.search(r"不|别|无需|不用", clause):
            continue
        if re.match(r"^(?:我要|我想|我需要|请帮我|帮我|请求)投诉", clause.strip()):
            return "complaint"
    if re.fullmatch(
        r"(?:你好|您好|嗨|哈喽|hello|hi|谢谢|再见|早上好|晚上好|你是谁)[！!。.?？\s]*", text
    ):
        return "other"
    return "knowledge"
