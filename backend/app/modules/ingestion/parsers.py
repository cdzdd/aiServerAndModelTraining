from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

ERROR_MESSAGES = {
    "NO_TEXT": "未提取到文本；扫描 PDF 需要先进行 OCR",
    "INVALID_FORMAT": "文件损坏或格式无效，请检查后重新上传",
    "PARSE_LIMIT": "文档页数或展开后的文本超过处理上限",
    "PARSE_TIMEOUT": "文档解析超时，请缩小文件后重试",
    "TOKENIZER_UNAVAILABLE": "分词模型尚未配置，请联系管理员",
    "PARSE_FAILED": "文档解析失败，请检查文件后重试",
    "SUPERSEDED": "任务对应的版本已被替换或停用",
}
MAX_TEXT = 2_000_000
MAX_PAGES = 2000


class ParseError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass
class Section:
    text: str
    page_number: int | None = None
    paragraph_number: int | None = None
    line_number: int | None = None


def parse_file(path: Path, file_type: str) -> list[Section]:
    sections = []
    total = 0

    def append(text, **location):
        nonlocal total
        text = text.replace("\x00", "")
        total += len(text)
        if total > MAX_TEXT or len(sections) >= 20_000:
            raise ParseError("PARSE_LIMIT")
        if text.strip():
            sections.append(Section(text, **location))

    try:
        if file_type in {"txt", "md"}:
            for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
                append(line, line_number=index)
        elif file_type == "docx":
            with ZipFile(path) as archive:
                if sum(entry.file_size for entry in archive.infolist()) > 40 * 1024 * 1024:
                    raise ParseError("PARSE_LIMIT")
            doc = Document(path)
            for index, block in enumerate(doc.iter_inner_content(), 1):
                if isinstance(block, Paragraph):
                    append(block.text, paragraph_number=index)
                else:
                    for row_index, row in enumerate(block.rows, 1):
                        append(
                            " | ".join(cell.text for cell in row.cells),
                            paragraph_number=index,
                            line_number=row_index,
                        )
        elif file_type == "pdf":
            reader = PdfReader(path, strict=True)
            if reader.is_encrypted:
                raise ParseError("INVALID_FORMAT")
            if len(reader.pages) > MAX_PAGES:
                raise ParseError("PARSE_LIMIT")
            for index, page in enumerate(reader.pages, 1):
                append(page.extract_text() or "", page_number=index)
        else:
            raise ParseError("INVALID_FORMAT")
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError("INVALID_FORMAT") from exc
    if not sections:
        raise ParseError("NO_TEXT")
    return sections
