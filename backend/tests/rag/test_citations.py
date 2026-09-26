import json
from uuid import UUID

import pytest

from app.modules.retrieval.schemas import SearchHit


def hit(**changes):
    values = dict(
        chunk_id=UUID(int=1),
        kb_id=UUID(int=2),
        source_id=UUID(int=3),
        revision_id=UUID(int=4),
        source_type="document",
        title="图书馆规定",
        text="开放时间为九点至十七点。周末闭馆。",
        score=0.9,
        page_number=2,
        paragraph_number=3,
        line_number=7,
    )
    return SearchHit(**(values | changes))


def select(selections, status="answered", **extra):
    return json.dumps(dict(status=status, selections=selections) | extra, ensure_ascii=False)


def test_quotes_and_metadata_only_come_from_selected_actual_prompt_hits():
    from app.modules.rag.citations import render_answer, validate_selection

    unused = hit(chunk_id=UUID(int=8))
    selected = hit()
    status, citations, used = validate_selection(
        select([dict(index=2, quote="  九点至十七点。  ")]), [unused, selected]
    )
    assert status == "answered"
    assert used == [selected]
    assert len(citations) == 1
    assert citations[0].model_dump(mode="json") == {
        "index": 2,
        "chunk_id": str(UUID(int=1)),
        "kb_id": str(UUID(int=2)),
        "source_id": str(UUID(int=3)),
        "revision_id": str(UUID(int=4)),
        "source_type": "document",
        "title": "图书馆规定",
        "quote": "九点至十七点。",
        "faq_version": None,
        "page_number": 2,
        "paragraph_number": 3,
        "line_number": 7,
    }
    assert render_answer(citations) == "资料原文：九点至十七点。 [2]"


@pytest.mark.parametrize("index", [True, False, 0, -1, 2, 99, 1.0, "1", str(UUID(int=1))])
def test_rejects_unknown_and_noninteger_index(index):
    from app.modules.rag.citations import validate_selection
    from app.modules.rag.schemas import RAGError

    with pytest.raises(RAGError, match="INVALID_CITATION"):
        validate_selection(select([dict(index=index, quote="九点")]), [hit()])


@pytest.mark.parametrize("quote", ["八点", "九点十七点", "", "  ", None, 9, "周末开馆。"])
def test_rejects_fabricated_noncontiguous_or_empty_quotes(quote):
    from app.modules.rag.citations import validate_selection
    from app.modules.rag.schemas import RAGError

    with pytest.raises(RAGError, match="INVALID_CITATION"):
        validate_selection(select([dict(index=1, quote=quote)]), [hit()])


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '```json\n{"status":"no_answer","selections":[]}\n```',
        "[]",
        "null",
        "{}",
        '{"status":"answered","selections":[]}',
        '{"status":"unknown","selections":[]}',
        '{"status":"no_answer","selections":[],"answer":"九点"}',
        '{"status":"no_answer","status":"clarify","selections":[]}',
        '{"status":"answered","selections":[{"index":1,"index":1,"quote":"九点"}]}',
        '{"status":"answered","selections":[{"index":1,"quote":"九点","title":"伪造"}]}',
        '{"status":"answered","selections":[{"index":1,"quote":"九点"},{"index":1,"quote":"闭馆"}]}',
        '{"status":"clarify","selections":[{"index":1,"quote":"九点"}]}',
        '{"status":"answered","selections":null}',
    ],
)
def test_rejects_invalid_structure_extra_fields_and_duplicate_ids(raw):
    from app.modules.rag.citations import validate_selection
    from app.modules.rag.schemas import RAGError

    with pytest.raises(RAGError, match="INVALID_CITATION"):
        validate_selection(raw, [hit()])


def test_quote_must_belong_to_exact_index_not_another_source():
    from app.modules.rag.citations import validate_selection
    from app.modules.rag.schemas import RAGError

    with pytest.raises(RAGError, match="INVALID_CITATION"):
        validate_selection(select([dict(index=1, quote="八点")]), [hit(), hit(text="八点")])


@pytest.mark.parametrize("status", ["clarify", "no_answer"])
def test_business_abstention_has_no_sources(status):
    from app.modules.rag.citations import validate_selection

    assert validate_selection(select([], status), [hit()]) == (status, [], [])


def test_faq_keeps_its_server_version_and_does_not_normalize_unicode():
    from app.modules.rag.citations import validate_selection
    from app.modules.rag.schemas import RAGError

    faq = hit(source_type="faq", revision_id=None, faq_version=3, text="Ａ卡补办")
    _, citations, _ = validate_selection(select([dict(index=1, quote="Ａ卡")]), [faq])
    assert citations[0].faq_version == 3
    assert citations[0].revision_id is None
    with pytest.raises(RAGError, match="INVALID_CITATION"):
        validate_selection(select([dict(index=1, quote="A卡")]), [faq])


def test_selection_count_and_total_quote_budget():
    from app.modules.rag.citations import validate_selection
    from app.modules.rag.schemas import RAGError

    hits = [hit(chunk_id=UUID(int=i + 1), text="文" * 801) for i in range(4)]
    for selections in [
        [dict(index=i + 1, quote="文") for i in range(4)],
        [dict(index=1, quote="文" * 401), dict(index=2, quote="文" * 400)],
    ]:
        with pytest.raises(RAGError, match="INVALID_CITATION"):
            validate_selection(select(selections), hits)
    _, citations, _ = validate_selection(select([dict(index=1, quote="文" * 800)]), hits)
    assert len(citations[0].quote) == 800
