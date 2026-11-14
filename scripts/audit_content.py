"""Non-destructive editorial audit of the original Notion export.

Reports potential duplicate titles, placeholder entries, and existing metadata
without altering source files or inventing relationships between articles.
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content" / "notion"
STABLE_ID = re.compile(r"[a-f0-9]{32}\.md$", re.I)
PLACEHOLDERS = {"тема", "личность", "цитата", "название работы", "направление"}

def substantive_body(lines):
    """Remove exported property rows without modifying the source."""
    remaining = list(lines[1:])
    while remaining and not remaining[0].strip():
        remaining.pop(0)
    while remaining and re.match(r'^[^#>\-*\[\n]{1,35}: ', remaining[0]):
        remaining.pop(0)
    return "\n".join(remaining).strip()


def opening_paragraph(body):
    """Return the first prose block, ignoring leading Markdown headings."""
    blocks = re.split(r'\n\s*\n', body)
    for block in blocks:
        block = block.strip()
        if not block or block.startswith(('#', '!', '|', '-', '*', '>', '```')):
            continue
        if re.fullmatch(r'\[[^]]+\]\([^)]*\)', block):
            continue
        return re.sub(r'\[[^]]+\]\([^)]*\)', '', block).strip()
    return ""


def audit():
    titles = defaultdict(list)
    placeholders = []
    invalid_names = []
    entries = []
    for file in sorted(CONTENT.rglob("*.md")):
        if not STABLE_ID.search(file.name):
            invalid_names.append(file.relative_to(ROOT).as_posix())
            continue
        lines = file.read_text(encoding="utf-8").splitlines()
        title = (lines[0].removeprefix("# ").strip() if lines else "")
        section = file.parent.name
        relative = file.relative_to(ROOT).as_posix()
        if not title or title.casefold() in PLACEHOLDERS:
            placeholders.append({"section": section, "title": title or "(empty)", "path": relative})
        titles[(section, title.casefold())].append(relative)
        body = substantive_body(lines)
        intro = opening_paragraph(body)
        relations = len(set(re.findall(r'[a-f0-9]{32}\.md', file.read_text(encoding="utf-8"), re.I)))
        body_chars = len(re.sub(r'\s+', ' ', body).strip())
        findings = []
        if body_chars == 0:
            findings.append("empty_body")
        elif body_chars < 350 and section != "Цитаты":
            findings.append("stub")
        if section == "Темы":
            if not intro:
                findings.append("missing_intro")
            elif not 100 <= len(intro) <= 650:
                findings.append("intro_length_review")
        if relations == 0 and section in ("Темы", "Личности", "История философии"):
            findings.append("no_explicit_internal_links")
        entries.append({
            "section": section, "title": title, "path": relative,
            "body_chars": body_chars, "intro_chars": len(intro),
            "explicit_internal_refs": relations, "findings": findings,
        })
    duplicates = [
        {"section": section, "title": title, "paths": paths}
        for (section, title), paths in sorted(titles.items())
        if title and len(paths) > 1
    ]
    by_finding = {kind: sum(kind in row["findings"] for row in entries)
                  for kind in ("empty_body", "stub", "missing_intro",
                               "intro_length_review", "no_explicit_internal_links")}
    return {
        "pages": len(entries),
        "possible_duplicates": duplicates,
        "possible_placeholders": placeholders,
        "invalid_filenames": invalid_names,
        "finding_counts": by_finding,
        "entries": entries,
        "note": "Heuristic editorial inventory. Links in CSV and automatically generated backlinks are not counted as explicit Markdown refs. No source files were changed.",
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write audit as JSON")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero on findings (opt-in)")
    args = parser.parse_args()
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.strict and any(result[key] for key in ("possible_duplicates", "possible_placeholders", "invalid_filenames")):
        raise SystemExit(1)

if __name__ == "__main__":
    main()
