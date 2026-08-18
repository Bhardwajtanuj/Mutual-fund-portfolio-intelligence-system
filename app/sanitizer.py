"""
Runs on every free-text field before it goes anywhere near the LLM: investor
notes, and (if the RAG layer is enabled) factsheet snippets pulled from the
web. Doesn't try to be clever NLP - just catches the common shape of an
injection attempt and quarantines it, and always wraps whatever survives in
explicit data/instruction delimiters.
"""
import re

INJECTION_PATTERNS = [
    r"\bignore (all|any|the)? ?(previous|prior|above)?\s*instructions?\b",
    r"\bdisregard (all|any|the)? ?(previous|prior|above)?\s*instructions?\b",
    r"\byou are now\b",
    r"\bnew system prompt\b",
    r"\breveal (your|the) (system prompt|instructions)\b",
    r"\bact as\b",
    r"```",  # code-fence used to try to break out of a data block
    r"<\s*/?(system|assistant|user)\s*>",  # fake role tags
    r"\brecommend (fund|scheme)\b.*\b(instead|no matter)\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def sanitize_text(text: str | None, field_name: str) -> tuple[str | None, list[str]]:
    """
    Returns (cleaned_text_or_None, warnings). If a field looks like an
    injection attempt, it's dropped entirely rather than partially cleaned -
    partial cleaning of adversarial text is unreliable.
    """
    if not text:
        return text, []

    hits = [p.pattern for p in _COMPILED if p.search(text)]
    if hits:
        return None, [f"Field '{field_name}' excluded - matched injection pattern(s): {hits}"]

    return text, []


def wrap_as_untrusted(text: str, source: str) -> str:
    """Explicit data/instruction delimiter for anything that does pass through."""
    return f"<untrusted_data source=\"{source}\">\n{text}\n</untrusted_data>"
