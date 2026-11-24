"""Automated verification harness for all 12 AURA lab assignments.

Compiles each lab script with `py_compile` and executes it as an isolated
subprocess from BOTH the repository root and the lab's own directory (24 runs),
using PYTHONDONTWRITEBYTECODE=1 so zero untracked cache artifacts remain.
"""

from __future__ import annotations

import os
import py_compile
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple


def discover_lab_scripts(assignments_dir: Path) -> List[Path]:
    scripts = sorted(assignments_dir.glob("Lab[0-9][0-9]_*/lab[0-9][0-9]_*.py"))
    if len(scripts) != 12:
        raise RuntimeError(f"Expected 12 lab scripts under {assignments_dir}, found {len(scripts)}.")
    return scripts


def run_check(script: Path, cwd: Path) -> Tuple[bool, float, str]:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-B", str(script)],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip().splitlines()[-1]
        return False, elapsed_ms, detail
    return True, elapsed_ms, "PASS"


def main() -> int:
    assignments_dir = Path(__file__).resolve().parent
    repo_root = assignments_dir.parent
    scripts = discover_lab_scripts(assignments_dir)

    print(f"Discovered {len(scripts)} lab assignments under {assignments_dir}\n")
    print(f"{'Lab Script':<44} | {'Compile':<7} | {'Root CWD':<14} | {'Lab CWD':<14}")
    print("-" * 88)

    all_passed = True
    for script in scripts:
        py_compile.compile(str(script), doraise=True)
        ok_root, ms_root, detail_root = run_check(script, repo_root)
        ok_lab, ms_lab, detail_lab = run_check(script, script.parent)
        all_passed = all_passed and ok_root and ok_lab

        root_col = f"PASS ({ms_root:.0f}ms)" if ok_root else f"FAIL: {detail_root[:10]}"
        lab_col = f"PASS ({ms_lab:.0f}ms)" if ok_lab else f"FAIL: {detail_lab[:10]}"
        print(f"{script.name:<44} | {'OK':<7} | {root_col:<14} | {lab_col:<14}")

        if not ok_root:
            print(f"  [ERROR root-cwd] {script.name}: {detail_root}")
        if not ok_lab:
            print(f"  [ERROR lab-cwd]  {script.name}: {detail_lab}")

    print("-" * 88)
    total_runs = len(scripts) * 2
    if all_passed:
        print(f"SUMMARY: 12/12 labs compiled and passed all {total_runs}/{total_runs} subprocess runs.")
        return 0
    print("SUMMARY: One or more labs failed verification.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
