"""Chinese character bigrams and complete ASCII identifiers, no extra tokenizer."""

import re
import unicodedata


def tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    result = set(re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", normalized))
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        result.update(run[index : index + 2] for index in range(max(1, len(run) - 1)))
    return result


def lexical_score(query: str, text: str) -> float:
    terms = tokens(query)
    return len(terms.intersection(tokens(text))) / len(terms) if terms else 0.0
