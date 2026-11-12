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

def audit():
    titles = defaultdict(list)
    placeholders = []
    invalid_names = []
    total = 0
    for file in sorted(CONTENT.rglob("*.md")):
        if not STABLE_ID.search(file.name):
            invalid_names.append(file.relative_to(ROOT).as_posix())
            continue
        lines = file.read_text(encoding="utf-8").splitlines()
        title = (lines[0].removeprefix("# ").strip() if lines else "").strip()
        section = file.parent.name
        relative = file.relative_to(ROOT).as_posix()
        if not title:
            placeholders.append({"section": section, "title": "(empty)", "path": relative})
        elif title.casefold() in PLACEHOLDERS:
            placeholders.append({"section": section, "title": title, "path": relative})
        titles[(section, title.casefold())].append(relative)
        total += 1
    duplicates = [
        {"section": section, "title": title, "paths": paths}
        for (section, title), paths in sorted(titles.items())
        if title and len(paths) > 1
    ]
    return {
        "pages": total,
        "possible_duplicates": duplicates,
        "possible_placeholders": placeholders,
        "invalid_filenames": invalid_names,
        "note": "Review manually; same titles and placeholders can be intentional. No export files were changed."
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
