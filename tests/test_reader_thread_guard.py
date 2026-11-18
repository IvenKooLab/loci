"""The OCR path must not leak rapidocr's subprocess-reader crashes.

rapidocr probes for tesseract with subprocess(text=True); on a Chinese
Windows host in UTF-8 mode the GBK answers kill the reader thread with
UnicodeDecodeError. loci cannot fix the probe, so it mutes exactly that
failure shape while an OCR call runs — everything else stays loud.
"""
from __future__ import annotations

import threading

from loci.loaders import _tolerant_child_output


def _raise_in_thread(exc, name):
    t = threading.Thread(target=_raiser, args=(exc,), name=name, daemon=True)
    t.start()
    t.join()


def _raiser(exc):
    raise exc


def test_reader_thread_decode_error_is_muted_inside_the_guard():
    seen = []
    default = threading.excepthook
    threading.excepthook = lambda args: seen.append(args.exc_type)
    try:
        with _tolerant_child_output():
            _raise_in_thread(UnicodeDecodeError("utf-8", b"\xd0", 0, 1, "bad"),
                             "Thread-8 (_readerthread)")
        _raise_in_thread(ValueError("other"), "Thread-9 (_readerthread)")
    finally:
        threading.excepthook = default
    assert seen == [ValueError]           # decode error swallowed, others pass


def test_guard_restores_the_default_hook():
    before = threading.excepthook
    with _tolerant_child_output():
        assert threading.excepthook is not before
    assert threading.excepthook is before
