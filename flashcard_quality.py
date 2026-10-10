"""Quality helpers for the DarsYar flashcard bank.

Cards must be authored as distinct educational items; this module intentionally
does not manufacture paraphrases to inflate per-book counts.
"""
import re
import unicodedata
from collections.abc import Iterable

def normalize_text(value: str) -> str:
    """Normalize Persian/Arabic variants and punctuation for duplicate checks."""
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = value.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    value = re.sub(r"[\u064b-\u065f\u0670]", "", value)
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())

def deduplicate_cards(cards: Iterable[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Keep the first card for each normalized question within its subject."""
    result = []
    seen = set()
    for card in cards:
        if len(card) != 3:
            continue
        subject, question, answer = (str(part).strip() for part in card)
        key = (normalize_text(subject), normalize_text(question))
        if not subject or not question or not answer or key in seen:
            continue
        seen.add(key)
        result.append((subject, question, answer))
    return result

def duplicate_questions(cards: Iterable[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """Return exact/normalization-level duplicate questions for quality reports."""
    seen = set()
    duplicates = []
    for subject, question, _answer in cards:
        key = (normalize_text(subject), normalize_text(question))
        if key in seen:
            duplicates.append((subject, question))
        else:
            seen.add(key)
    return duplicates
