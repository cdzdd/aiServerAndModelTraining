from dataclasses import replace
from functools import lru_cache

from tokenizers import Tokenizer

from app.modules.ingestion.parsers import ParseError, Section


@lru_cache(maxsize=2)
def load_tokenizer(path: str) -> Tokenizer:
    try:
        tokenizer = Tokenizer.from_file(path)
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return tokenizer
    except Exception as exc:
        raise ParseError("TOKENIZER_UNAVAILABLE") from exc


def split_sections(sections: list[Section], tokenizer: Tokenizer) -> list[Section]:
    chunks = []
    for section in sections:
        encoded = tokenizer.encode(section.text, add_special_tokens=False)
        count = len(encoded.ids)
        offsets = encoded.offsets
        word_ids = encoded.word_ids
        start = 0
        while start < count:
            end = min(start + 400, count)
            while end > start:
                # A continuation piece may tokenize differently as a new word.
                if end < count and word_ids[end] == word_ids[end - 1]:
                    end -= 1
                    continue
                left = 0 if start == 0 else offsets[start][0]
                right = len(section.text) if end == count else offsets[end][0]
                text = section.text[left:right]
                if len(tokenizer.encode(text, add_special_tokens=False).ids) <= 400:
                    break
                end -= 1
            if end == start:
                raise ParseError("PARSE_LIMIT")
            chunks.append(replace(section, text=text))
            if end == count:
                break
            # Target 50 tokens; expand overlap to preserve a complete WordPiece word.
            following = max(start + 1, end - 50)
            while following > start and word_ids[following] == word_ids[following - 1]:
                following -= 1
            if following <= start:
                raise ParseError("PARSE_LIMIT")
            start = following
    if not chunks:
        raise ParseError("NO_TEXT")
    return chunks
