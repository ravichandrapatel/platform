#!/usr/bin/env python3
"""
Merge Trivy config + fs JSON outputs into trivy-results.json with scan_date.
Optionally print Critical vulnerability count from trivy-results.json (for CI).
Uses only stdlib: json, os, argparse, datetime.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime


def merge_results(dir_path: str, scan_date: str | None = None) -> None:
    """Read trivy-config.json and trivy-fs.json from dir_path, write trivy-results.json.
    Trivy may not create one of the files (e.g. if the folder is empty); we handle missing
    files via os.path.isfile and merge whatever exists. Write only if at least one exists.
    """
    if scan_date is None:
        scan_date = datetime.utcnow().strftime("%Y-%m-%d")
    cfg: dict = {}
    fs: dict = {}
    cfg_path = os.path.join(dir_path, "trivy-config.json")
    fs_path = os.path.join(dir_path, "trivy-fs.json")
    if os.path.isfile(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
    if os.path.isfile(fs_path):
        with open(fs_path, encoding="utf-8") as f:
            fs = json.load(f)
    # Only write if at least one Trivy output existed (avoid empty merge when both steps failed)
    if not os.path.isfile(cfg_path) and not os.path.isfile(fs_path):
        return
    out = {"scan_date": scan_date, "config": cfg, "fs": fs}
    out_path = os.path.join(dir_path, "trivy-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=0)


def count_critical(dir_path: str) -> int:
    """Return number of CRITICAL vulnerabilities in trivy-results.json."""
    path = os.path.join(dir_path, "trivy-results.json")
    if not os.path.isfile(path):
        return -1
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    c = 0
    for key in ("config", "fs"):
        part = d.get(key)
        if not isinstance(part, dict):
            continue
        for r in part.get("Results") or []:
            for v in r.get("Vulnerabilities") or []:
                if (v.get("Severity") or "").upper() == "CRITICAL":
                    c += 1
    return c


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge Trivy results or print Critical count")
    parser.add_argument("--dir", default=".", help="Directory containing trivy-*.json (default: cwd)")
    parser.add_argument("--scan-date", help="Scan date YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--print-critical-count", action="store_true", help="Print Critical count from trivy-results.json and exit")
    args = parser.parse_args()
    dir_path = os.path.abspath(args.dir)

    if args.print_critical_count:
        n = count_critical(dir_path)
        print(n)
        return
    merge_results(dir_path, args.scan_date)


if __name__ == "__main__":
    main()
