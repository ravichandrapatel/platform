#!/usr/bin/env python3
"""
FILE_NAME: update_readme.py
DESCRIPTION: Compliance updater (upsert mode). Writes compliance table to compliance.md (with optional badge);
  updates readme.md with badge and link. Loads table between markers, merges trivy-results.json, writes via temp file. Stdlib only.
VERSION: 1.0.0
EXIT_CODES: 0 = success, non-zero on missing markers or I/O error
AUTHORS: Platform / DevOps
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile

START_MARKER = "<!-- COMPLIANCE_TABLE_START -->"
END_MARKER = "<!-- COMPLIANCE_TABLE_END -->"
BADGE_MARKER = "<!-- COMPLIANCE_BADGE -->"


def find_root() -> str:
    """INTENT: Return platform root directory (contains images/ and readme.md). INPUT: None. OUTPUT: str. SIDE_EFFECTS: Disk (isdir/isfile)."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(script_dir)
    if os.path.isdir(os.path.join(root, "images")) and os.path.isfile(
        os.path.join(root, "readme.md")
    ):
        return root
    parent = os.path.dirname(root)
    if os.path.isdir(os.path.join(parent, "images")) and os.path.isfile(
        os.path.join(parent, "readme.md")
    ):
        return parent
    return root


def images_with_trivy_results(root: str) -> list[str]:
    """INTENT: Return list of image names under images/ that have trivy-results.json. INPUT: root (str). OUTPUT: list[str]. SIDE_EFFECTS: Disk (listdir, isfile)."""
    images_dir = os.path.join(root, "images")
    if not os.path.isdir(images_dir):
        return []
    out = []
    for name in sorted(os.listdir(images_dir)):
        path = os.path.join(images_dir, name, "trivy-results.json")
        if os.path.isfile(path):
            out.append(name)
    return out


def count_vulnerabilities(data: dict) -> tuple[int, int, int]:
    """INTENT: Return (critical, high, medium) counts from Trivy-style JSON. INPUT: data (dict). OUTPUT: tuple[int,int,int]. SIDE_EFFECTS: None."""
    c, h, m = 0, 0, 0
    results = data.get("Results") or []
    for r in results:
        for v in (r.get("Vulnerabilities") or []):
            sev = (v.get("Severity") or "").upper()
            if sev == "CRITICAL":
                c += 1
            elif sev == "HIGH":
                h += 1
            elif sev == "MEDIUM":
                m += 1
    return c, h, m


def row_from_trivy_results(root: str, image_name: str) -> dict[str, str] | None:
    """INTENT: Read trivy-results.json for image and return row dict (image_name, status, vuln, date). INPUT: root, image_name (str). OUTPUT: dict | None. SIDE_EFFECTS: Disk read."""
    path = os.path.join(root, "images", image_name, "trivy-results.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    last_scan = raw.get("scan_date") or "-"
    c, h, m = 0, 0, 0
    for key in ("config", "fs"):
        part = raw.get(key)
        if isinstance(part, dict):
            dc, dh, dm = count_vulnerabilities(part)
            c, h, m = c + dc, h + dh, m + dm
    if c == 0 and h == 0 and m == 0 and "Results" in raw:
        c, h, m = count_vulnerabilities(raw)

    status = "✅" if c == 0 else "❌"
    vuln = f"{c}/{h}/{m}"
    return {
        "image_name": image_name,
        "status": status,
        "vuln": vuln,
        "date": last_scan,
    }


def parse_table_from_markdown(table_text: str) -> list[dict[str, str]]:
    """INTENT: Parse Markdown table into list of row dicts (Image Name | Status | Vulnerabilities | Last Scan Date).
    INPUT: table_text (str). OUTPUT: list[dict]. SIDE_EFFECTS: None."""
    rows = []
    lines = [ln.strip() for ln in table_text.strip().splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if not line.startswith("|") or not line.endswith("|"):
            continue
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) < 4:
            continue
        if i == 0 and "Image Name" in (parts[0] or ""):
            continue
        if re.match(r"^[-:]+$", parts[0] or ""):
            continue
        rows.append({
            "image_name": parts[0].strip(),
            "status": parts[1].strip() if len(parts) > 1 else "-",
            "vuln": parts[2].strip() if len(parts) > 2 else "-",
            "date": parts[3].strip() if len(parts) > 3 else "-",
        })
    return rows


def table_to_markdown(rows: list[dict[str, str]]) -> str:
    """INTENT: Convert list of row dicts to Markdown table string. INPUT: rows (list[dict]). OUTPUT: str. SIDE_EFFECTS: None."""
    header = "| Image Name | Status | Vulnerabilities (C/H/M) | Last Scan Date |"
    sep = "|------------|--------|--------------------------|----------------|"
    body = []
    for r in rows:
        body.append(f"| {r['image_name']} | {r['status']} | {r['vuln']} | {r['date']} |")
    return "\n".join([header, sep] + body)


def _is_placeholder_row(row: dict[str, str]) -> bool:
    """INTENT: Return True if row looks like a placeholder (e.g. 'Run the workflow...'). INPUT: row (dict). OUTPUT: bool. SIDE_EFFECTS: None."""
    name = (row.get("image_name") or "").strip()
    return name.startswith("*") or "run the" in name.lower() or name == "-"


def upsert_rows(
    existing_rows: list[dict[str, str]],
    new_rows_by_name: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """INTENT: Merge new scan rows into existing; replace by image_name, skip placeholders when we have real data, append new images.
    INPUT: existing_rows, new_rows_by_name. OUTPUT: list[dict]. SIDE_EFFECTS: None."""
    seen = set()
    out = []
    have_new = bool(new_rows_by_name)
    for row in existing_rows:
        name = row.get("image_name") or ""
        if name in new_rows_by_name:
            out.append(new_rows_by_name[name])
            seen.add(name)
        elif have_new and _is_placeholder_row(row):
            continue
        else:
            out.append(row)
    for name, row in sorted(new_rows_by_name.items()):
        if name not in seen:
            out.append(row)
    return out


def read_table_between_markers(
    content: str, start_marker: str, end_marker: str
) -> tuple[str, str, str]:
    """INTENT: Split content into (before, table_block, after) by markers. INPUT: content, start_marker, end_marker. OUTPUT: tuple[str,str,str]. Raises if markers missing. SIDE_EFFECTS: None."""
    pattern = re.compile(
        re.escape(start_marker) + r"\s*(.*?)\s*" + re.escape(end_marker),
        re.DOTALL,
    )
    m = pattern.search(content)
    if not m:
        raise SystemExit(
            f"Markers {start_marker!r} and {end_marker!r} not found."
        )
    before = content[: m.start()]
    table_block = m.group(1).strip()
    after = content[m.end() :]
    return before, table_block, after


def badge_markdown(repo: str) -> str:
    """INTENT: Return status badge markdown for compliance workflow. INPUT: repo (str, owner/repo). OUTPUT: str. SIDE_EFFECTS: None."""
    base = f"https://github.com/{repo}/actions/workflows/compliance.yml"
    return f"[![Compliance]({base}/badge.svg)]({base})"


def safe_write(path: str, content: str) -> None:
    """INTENT: Write content to path atomically (temp file then replace). INPUT: path, content (str). OUTPUT: None. SIDE_EFFECTS: Disk. Raises on error."""
    fd, tmp_path = tempfile.mkstemp(
        prefix="compliance_", suffix=".md", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        # _log("[ERR-T-01] safe_write failed, cleaning temp file")
        if os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def update_compliance_md(root: str, repo: str | None) -> None:
    """INTENT: Write or update compliance.md (badge if repo, full table between markers); upsert scan data from trivy-results.json.
    INPUT: root (str), repo (str | None). OUTPUT: None. SIDE_EFFECTS: Disk read/write."""
    # _log("[T-01] Updating compliance.md")
    compliance_path = os.path.join(root, "compliance.md")
    if os.path.isfile(compliance_path):
        with open(compliance_path, encoding="utf-8") as f:
            content = f.read()
    else:
        content = (
            "# Compliance\n\n"
            + BADGE_MARKER + "\n\n## Status\n\n"
            + START_MARKER + "\n| Image Name | Status | Vulnerabilities (C/H/M) | Last Scan Date |\n"
            "|------------|--------|--------------------------|----------------|\n"
            "| *Run the compliance workflow to populate this table.* | - | - | - |\n"
            + END_MARKER + "\n"
        )

    # Replace badge placeholder
    if repo:
        badge = badge_markdown(repo)
        content = content.replace(BADGE_MARKER, badge, 1)

    before, table_block, after = read_table_between_markers(
        content, START_MARKER, END_MARKER
    )
    existing_rows = parse_table_from_markdown(table_block)

    scanned = images_with_trivy_results(root)
    new_rows_by_name = {}
    for name in scanned:
        row = row_from_trivy_results(root, name)
        if row:
            new_rows_by_name[name] = row

    merged = upsert_rows(existing_rows, new_rows_by_name)
    new_table = table_to_markdown(merged)
    # _log("[T-02] Writing compliance.md")
    new_content = before + START_MARKER + "\n" + new_table + "\n" + END_MARKER + after
    safe_write(compliance_path, new_content)


def update_readme_section(root: str, repo: str | None) -> None:
    """INTENT: Replace compliance section in readme.md with badge + link to compliance.md. INPUT: root, repo (str | None). OUTPUT: None. SIDE_EFFECTS: Disk read/write."""
    readme_path = os.path.join(root, "readme.md")
    with open(readme_path, encoding="utf-8") as f:
        content = f.read()

    if START_MARKER not in content or END_MARKER not in content:
        return

    before, _, after = read_table_between_markers(content, START_MARKER, END_MARKER)
    if repo:
        badge = badge_markdown(repo)
        block = f"{badge}\n\nFull table: [compliance.md](compliance.md)"
    else:
        block = "Full table: [compliance.md](compliance.md)"
    new_content = before + START_MARKER + "\n" + block + "\n" + END_MARKER + after
    safe_write(readme_path, new_content)


def main() -> None:
    """INTENT: Parse args, find root, update compliance.md and readme section. INPUT: None (argv). OUTPUT: None. SIDE_EFFECTS: Disk, stdout."""
    # _log("[T-01] Starting compliance updater")
    parser = argparse.ArgumentParser(description="Update compliance table and badges")
    parser.add_argument(
        "--repo",
        metavar="OWNER/REPO",
        help="GitHub repo (e.g. myorg/myrepo) to render workflow status badge",
    )
    args = parser.parse_args()

    root = find_root()
    update_compliance_md(root, args.repo)
    update_readme_section(root, args.repo)
    print("Updated compliance.md and readme (upsert + badges).")


if __name__ == "__main__":
    main()
