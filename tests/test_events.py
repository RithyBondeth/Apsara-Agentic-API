"""Tests for text parsing and event formatting."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from apsara_cli.shared.text import format_rich_text_lines


# ── format_rich_text_lines ────────────────────────────────────────────────────

def _types(text: str) -> list[str]:
    return [item[0] for item in format_rich_text_lines(text, width=80)]


def _lines_of(text: str, kind: str) -> list[str]:
    return [item[1] for item in format_rich_text_lines(text, width=80) if item[0] == kind]


def test_plain_body():
    result = format_rich_text_lines("hello world", width=80)
    assert any(t == "body" for t, *_ in result)


def test_blank_line():
    result = format_rich_text_lines("first\n\nsecond", width=80)
    types = [t for t, *_ in result]
    assert "blank" in types


def test_bullet_list():
    text = "- item one\n- item two"
    types = _types(text)
    assert types.count("list") == 2


def test_ordered_list():
    text = "1. first\n2. second\n3. third"
    types = _types(text)
    assert types.count("list") == 3


def test_heading_detected():
    text = "Summary:\nsome body text"
    types = _types(text)
    assert "heading" in types


def test_code_block_emits_code_start_and_code():
    text = "```python\ndef foo():\n    pass\n```"
    result = format_rich_text_lines(text, width=80)
    types = [item[0] for item in result]
    assert "code_start" in types
    assert "code" in types


def test_code_block_captures_language():
    text = "```javascript\nconsole.log('hi')\n```"
    result = format_rich_text_lines(text, width=80)
    starts = [item for item in result if item[0] == "code_start"]
    assert len(starts) == 1
    assert starts[0][1] == "javascript"


def test_code_block_no_language():
    text = "```\nplain code\n```"
    result = format_rich_text_lines(text, width=80)
    starts = [item for item in result if item[0] == "code_start"]
    assert starts[0][1] == ""


def test_code_block_content():
    text = "```bash\nls -la\ncd /tmp\n```"
    code_lines = _lines_of(text, "code")
    assert "ls -la" in code_lines
    assert "cd /tmp" in code_lines


def test_multiple_code_blocks():
    text = "```python\nx = 1\n```\nsome text\n```bash\nls\n```"
    result = format_rich_text_lines(text, width=80)
    starts = [item for item in result if item[0] == "code_start"]
    assert len(starts) == 2


def test_no_trailing_blank():
    text = "hello"
    result = format_rich_text_lines(text, width=80)
    assert result[-1][0] != "blank"


def test_inline_markdown_stripped():
    text = "**bold** and `code` here"
    body_lines = _lines_of(text, "body")
    combined = " ".join(body_lines)
    assert "**" not in combined
    assert "`" not in combined
    assert "bold" in combined
    assert "code" in combined


def test_wrap_long_line():
    long_text = "word " * 40  # 200 chars, should wrap at width=40
    result = format_rich_text_lines(long_text.strip(), width=40)
    body_lines = [item[1] for item in result if item[0] == "body"]
    assert len(body_lines) > 1
    for line in body_lines:
        assert len(line) <= 44  # small tolerance for indent
