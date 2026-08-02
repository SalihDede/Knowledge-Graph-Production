from __future__ import annotations


def iter_paragraphs_with_offsets(text: str) -> list[tuple[str, int, int]]:
    """Splits `text` on blank lines and returns (paragraph, char_start,
    char_end) triples with offsets into the *original* `text` -- purely
    arithmetic (no re-searching), so it can't misattribute offsets when the
    same paragraph text repeats.
    """
    results: list[tuple[str, int, int]] = []
    cursor = 0
    for raw_paragraph in text.split("\n\n"):
        start = cursor
        end = start + len(raw_paragraph)
        stripped = raw_paragraph.strip()
        if stripped:
            leading_ws = len(raw_paragraph) - len(raw_paragraph.lstrip())
            trailing_ws = len(raw_paragraph) - len(raw_paragraph.rstrip())
            results.append((stripped, start + leading_ws, end - trailing_ws))
        cursor = end + 2  # length of the "\n\n" separator consumed by split()
    return results
