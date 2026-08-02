from __future__ import annotations

from ingestion.segmentation import iter_paragraphs_with_offsets


def test_splits_on_blank_lines_with_correct_offsets() -> None:
    text = "Para one.\n\nPara two.\n\nPara three."

    result = iter_paragraphs_with_offsets(text)

    assert [paragraph for paragraph, _, _ in result] == ["Para one.", "Para two.", "Para three."]
    for paragraph, start, end in result:
        assert text[start:end] == paragraph


def test_trims_whitespace_within_a_paragraph_while_keeping_offsets_accurate() -> None:
    text = "  Hello  \n\nWorld"

    result = iter_paragraphs_with_offsets(text)

    assert result[0][0] == "Hello"
    assert text[result[0][1]:result[0][2]] == "Hello"
    assert result[1] == ("World", 11, 16)


def test_skips_blank_paragraphs_from_extra_blank_lines() -> None:
    text = "A\n\n\n\nB"

    result = iter_paragraphs_with_offsets(text)

    assert [paragraph for paragraph, _, _ in result] == ["A", "B"]


def test_returns_empty_list_for_blank_text() -> None:
    assert iter_paragraphs_with_offsets("") == []
    assert iter_paragraphs_with_offsets("   \n\n   ") == []


def test_single_paragraph_with_no_blank_lines() -> None:
    text = "Just one paragraph here."

    result = iter_paragraphs_with_offsets(text)

    assert result == [(text, 0, len(text))]
