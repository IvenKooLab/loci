"""CLI output must not die on a non-UTF-8 code page.

Windows consoles that are piped or redirected encode with the ANSI code
page (cp936 on Chinese Windows), which has no slot for the emoji harness
icons: `loci harness --json > x.json` used to crash mid-print with
UnicodeEncodeError. The entry point degrades unencodable characters to
backslash escapes instead.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap


def test_emoji_output_survives_a_gbk_pipe():
    code = textwrap.dedent("""
        from loci.cli import _tolerant_output
        _tolerant_output()
        print("icon \u26a1 ok")
    """)
    env = {**os.environ, "PYTHONIOENCODING": "gbk",
           "PYTHONPATH": os.pathsep.join(sys.path)}
    proc = subprocess.run([sys.executable, "-c", code], env=env,
                          capture_output=True, text=True, encoding="gbk",
                          errors="replace", timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "icon" in proc.stdout and "ok" in proc.stdout


def test_utf8_console_is_left_alone():
    # On a UTF-8 stream the reconfigure must not swap the encoding itself.
    import io
    buf = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    original = buf.encoding
    saved_out, saved_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buf
    try:
        from loci.cli import _tolerant_output
        _tolerant_output()
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
    assert buf.encoding.lower().replace("-", "") == original.lower().replace("-", "")
