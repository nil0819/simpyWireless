# Rashed-Step 24.A-10-19-2026-start
"""
Step 24.A tests: the per-event log file is off by default and turned on by
common.common.enable_file_log() / --log-file.
"""
import logging
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from types import SimpleNamespace

from click.testing import CliRunner

import common.common as cc


def _off():
    cc._FILE_LOG_ON = False
    for h in list(logging.getLogger().handlers):
        logging.getLogger().removeHandler(h)
        h.close()


def test_off_by_default_and_on_when_enabled(tmp_path):
    _off()
    node = SimpleNamespace(col="", env=SimpleNamespace(now=12.5), name="AP 1")
    assert not cc.file_log_enabled()
    cc.log(node, "nothing written")                       # no handler, no file, returns at once
    path = str(tmp_path / "sub" / "run.log")
    try:
        assert cc.enable_file_log(path, "INFO") == path and cc.file_log_enabled()
        cc.log(node, "hello")
        for h in logging.getLogger().handlers:
            h.flush()
        text = open(path).read()
        assert "Time: 12.5 Station: AP 1 Message: hello" in text and "nothing written" not in text
    finally:
        _off()


def test_cli_flag():
    from singleRun import single_run
    base = ["--ap-number", "1", "--gnb-number", "1", "--seed", "1", "-t", "0.05", "-r", "1"]
    runner = CliRunner()
    with runner.isolated_filesystem():
        try:
            plain = runner.invoke(single_run, base)
            made_plain = os.path.isdir("log") and os.listdir("log")
            logged = runner.invoke(single_run, base + ["--log-file"])
            files = os.listdir("log") if os.path.isdir("log") else []
        finally:
            _off()
    assert plain.exit_code == 0 and logged.exit_code == 0, logged.output[-300:]
    assert not made_plain                                   # default: no log file
    assert "Log file: log/" in logged.output and len(files) == 1
    occ = lambda r: [l for l in r.output.splitlines() if "occupancy (Normalized)" in l]
    assert occ(plain) == occ(logged)                        # results don't depend on it
# Rashed-Step 24.A-10-19-2026-end
