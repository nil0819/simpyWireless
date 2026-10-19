# Rashed-Step 24.D-10-19-2026-start
"""
Step 24.D test: importing the simulator stays light (every parallel worker
re-imports it): no pandas, no scipy.stats.
"""
import os
import subprocess
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_simulator_import_does_not_pull_heavy_modules():
    code = ("import sys; import analysis.laa_fairness, analysis.parallel, simulation; "
            "heavy = [m for m in ('pandas', 'scipy.stats') if m in sys.modules]; print(heavy)")
    out = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip() == "[]"
# Rashed-Step 24.D-10-19-2026-end
