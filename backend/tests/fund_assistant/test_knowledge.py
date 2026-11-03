from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.modules.fund_assistant.import_knowledge import import_documents, load_markdown
from app.modules.ingestion.models import IngestionJob
from app.modules.knowledge.models import FAQ, KnowledgeBase


def test_small_markdown_input_rejects_unknown_files_duplicate_titles_and_oversize(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text("# 如何申购\n只介绍操作，不代为交易。", encoding="utf-8")
    assert load_markdown(tmp_path) == {"如何申购": "# 如何申购\n只介绍操作，不代为交易。"}
    other = tmp_path / "other.md"
    other.write_text("# 如何申购\n重复标题", encoding="utf-8")
    with pytest.raises(ValueError, match="unique title"):
        load_markdown(tmp_path)
    other.unlink()
    path.write_text("a" * 65537, encoding="utf-8")
    with pytest.raises(ValueError, match="too large"):
        load_markdown(tmp_path)
    path.unlink()
    (tmp_path / "secret.env").write_text("not a knowledge source", encoding="utf-8")
    with pytest.raises(ValueError, match="Only ordinary Markdown"):
        load_markdown(tmp_path)


def test_knowledge_input_does_not_follow_file_links(tmp_path):
    folder = tmp_path / "knowledge"
    folder.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("# 外部资料\n不应读取", encoding="utf-8")
    try:
        (folder / "guide.md").symlink_to(outside)
    except OSError:
        pytest.skip("This platform does not permit creating symbolic links")
    with pytest.raises(ValueError, match="Only ordinary Markdown"):
        load_markdown(folder)


def test_import_is_idempotent_versions_changes_and_never_modifies_other_kb(migrated_engine):
    factory = sessionmaker(migrated_engine, expire_on_commit=False)
    kb_id = uuid4()
    documents = {"规则说明": "# 规则说明\n仅模拟交易。", "账户说明": "# 账户说明\n按卡记录。"}
    with factory.begin() as db:
        first = import_documents(db, documents, kb_id)
        second = import_documents(db, documents, kb_id)
        assert first["changedCount"] == 2 and second["changedCount"] == 0
        assert not first["indexedByThisCommand"]
        assert len(list(db.scalars(select(IngestionJob).where(IngestionJob.kind == "index")))) == 2
        import_documents(db, {"规则说明": "# 规则说明\n更新规则，不代客操作。"}, kb_id)
        rows = {row.question: row for row in db.scalars(select(FAQ).where(FAQ.kb_id == kb_id))}
        assert rows["规则说明"].version == 2
        assert not rows["账户说明"].is_active
        unrelated = KnowledgeBase(name="原问答业务知识库", visibility="restricted")
        db.add(unrelated)
        db.flush()
        with pytest.raises(ValueError, match="not owned"):
            import_documents(db, documents, unrelated.id)
        assert unrelated.name == "原问答业务知识库"
