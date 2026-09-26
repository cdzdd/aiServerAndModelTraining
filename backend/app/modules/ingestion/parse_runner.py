"""Isolated parser child: bounded by the worker's hard process timeout."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.modules.ingestion.chunking import load_tokenizer, split_sections
from app.modules.ingestion.parsers import ParseError, parse_file


def main():
    try:
        from app.modules.ingestion.resource_limits import limit_memory

        limit_memory()
        sections = parse_file(Path(sys.argv[1]), sys.argv[2])
        chunks = split_sections(sections, load_tokenizer(sys.argv[3]))
        result = {"chunks": [asdict(chunk) for chunk in chunks]}
    except MemoryError:
        result = {"error": "PARSE_LIMIT"}
    except ParseError as exc:
        result = {"error": exc.code}
    except Exception:
        result = {"error": "PARSE_FAILED"}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
