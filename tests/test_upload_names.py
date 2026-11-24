"""Upload names are user input that lands on disk (the console's drop zone,
POST /upload).

_safe_upload_name kept the extension only by luck: it cut the name at 120
characters, so a long name lost ".pdf" and was then refused as an
unsupported type. It also passed through what Windows cannot create —
`<>:"|?*` (a colon is worse than forbidden: it names an alternate data
stream, so "report:evil.pdf" is written as a hidden stream of a file called
"report"), trailing dots and spaces (which Windows silently drops, so the
file on disk was not the name the caller was told), and the superscript and
console device names.
"""
from __future__ import annotations

import pytest

from loci.http_api import _safe_upload_name


def test_ordinary_names_pass_through_unchanged():
    for name in ("report.pdf", "notes 2026.md", "规格说明.docx", "a.b.c.txt",
                 "Screenshot 2026-11-24 at 10.30.45.png"):
        assert _safe_upload_name(name) == name, name


def test_path_parts_are_stripped():
    assert _safe_upload_name("../../etc/passwd.txt") == "passwd.txt"
    assert _safe_upload_name("C:\\Users\\me\\specs\\spec.pdf") == "spec.pdf"


def test_truncation_keeps_the_extension():
    kept = _safe_upload_name("a" * 130 + ".pdf")
    assert kept.endswith(".pdf") and len(kept) <= 120
    kept = _safe_upload_name("长" * 200 + ".docx")
    assert kept.endswith(".docx") and len(kept) <= 120


@pytest.mark.parametrize("given, expected", [
    ("report:evil.pdf", "report_evil.pdf"),
    ("q?.pdf", "q_.pdf"),
    ("a*b.txt", "a_b.txt"),
    ('say "hi".md', 'say _hi_.md'),
])
def test_characters_windows_cannot_create_are_replaced(given, expected):
    assert _safe_upload_name(given) == expected


def test_trailing_dots_and_spaces_are_removed():
    assert _safe_upload_name("report.pdf...") == "report.pdf"
    assert _safe_upload_name("notes.md . . ") == "notes.md"


@pytest.mark.parametrize("bad", [
    "CON", "con.md", "NUL.pdf", "COM1", "lpt3.txt",
    "COM¹.md", "com².txt", "LPT¹.pdf", "lpt³.md",         # superscript forms are reserved too
    "CONIN$.txt", "CONOUT$.md",                           # the console devices
    "con .txt", "aux  .pdf",                               # Windows drops the trailing spaces
])
def test_reserved_device_names_are_refused_in_every_form(bad):
    assert _safe_upload_name(bad) is None, bad


@pytest.mark.parametrize("bad", ["a\x00b.txt", "a\nb.txt", "a\rb.txt", "a\x7fb.txt"])
def test_control_characters_are_refused(bad):
    assert _safe_upload_name(bad) is None


@pytest.mark.parametrize("bad", ["", "  ", ".hidden.md", ".", "..", " . . ", " ... "])
def test_a_name_with_nothing_left_is_refused(bad):
    assert _safe_upload_name(bad) is None, bad


def test_a_name_of_only_forbidden_characters_is_cleaned_into_a_usable_one():
    assert _safe_upload_name(":.pdf") == "_.pdf"
