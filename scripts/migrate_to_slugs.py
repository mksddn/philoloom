"""One-time migration from export IDs to typed, human-readable entity keys."""
from pathlib import Path
import json
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "content/knowledge"
HEX = re.compile(r"([a-f0-9]{32})\.md$")
GROUPS = {"Темы": "topics", "Личности": "people", "История философии": "history",
          "Цитаты": "quotes", "Самостоятельная работа": "articles"}
LATIN = dict(zip("абвгдежзийклмнопрстуфхцчшщъыьэюя",
                 ["a","b","v","g","d","e","zh","z","i","i","k","l","m","n","o","p","r","s","t","u","f","h","ts","ch","sh","shch","","y","","e","yu","ya"]))

def slugify(s):
    s = s.lower().replace("ё", "е")
    s = "".join(LATIN.get(c, c) for c in s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:85].strip("-") or "entry"

slugs = json.loads((ROOT / "content/slugs.json").read_text())
mapping = {k: v.strip("/") for k, v in slugs.items()}
used = set(mapping.values())
files = sorted(DATA.rglob("*.md"))
for path in files:
    old = HEX.search(path.name)
    if not old:
        raise ValueError(f"Unrecognized content: {path}")
    key = old.group(1)
    if key not in mapping:
        if path.parent == DATA:
            mapping[key] = "home"
        else:
            group = GROUPS[path.parent.name]
            stem = path.name[:old.start()].rstrip()
            candidate = group + "/" + slugify(stem)
            base, n = candidate, 2
            while candidate in used:
                candidate = base + "-" + str(n)
                n += 1
            mapping[key] = candidate
            used.add(candidate)
assert len(set(mapping.values())) == len(mapping)
assert len(mapping) == len(files), (len(mapping), len(files))

def replace_links(s):
    def sub(m):
        key = mapping.get(m.group(2))
        return "(" + key + ".md)" if key else m.group(0)
    return re.sub(r"\(([^()\n]*?([a-f0-9]{32})\.md)\)", sub, s)

for path in files:
    key = HEX.search(path.name).group(1)
    new = (DATA / "index.md") if mapping[key] == "home" else path.parent / (mapping[key].split("/")[-1] + ".md")
    assert not new.exists(), new
    new.write_text(replace_links(path.read_text(encoding="utf-8")), encoding="utf-8")
    path.unlink()
for path in sorted(DATA.rglob("*.csv")):
    match = re.search(r" [a-f0-9]{32}(_all)?\.csv$", path.name)
    assert match, path
    new = path.with_name(path.name[:match.start()] + (match.group(1) or "") + ".csv")
    assert not new.exists(), new
    new.write_text(replace_links(path.read_text(encoding="utf-8-sig")), encoding="utf-8-sig")
    path.unlink()

ledger = ROOT / "content/quote-provenance.json"
data = json.loads(ledger.read_text())
data["quotes"] = {mapping[key]: value for key, value in data["quotes"].items()}
ledger.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
(ROOT / "content/slugs.json").unlink()

build = ROOT / "scripts/build.py"
s = build.read_text()
s = s.replace('"""Build a portable static reference from the original source dataset."""',
              '"""Build the Philoloom atlas from human-readable knowledge records."""')
s = s.replace("ID = re.compile(r'([a-f0-9]{32})(?:_all)?\\.(?:md|csv)$')",
              "ID = re.compile(r'((?:people|topics|history|quotes|articles)/[a-z0-9-]+)\\.md$')")
s = s.replace("    match = ID.search(path.name)\n    if not match:\n        raise ValueError(f'Page has no stable ID: {path.name}')",
              "    group = path.parent.name if path.parent != CONTENT else ''\n"
              "    key = ('home' if not group else GROUP_KEY[group] + '/' + path.stem)\n"
              "    match = (key,)")
s = s.replace("pages = {}\nfor path", "GROUP_KEY = {'Темы': 'topics', 'История философии': 'history', 'Цитаты': 'quotes', 'Личности': 'people', 'Самостоятельная работа': 'articles'}\npages = {}\nfor path")
s = s.replace("# IDs remain the source of truth; the checked-in map pins stable public URLs.\nSLUGS = json.loads((ROOT / 'content' / 'slugs.json').read_text(encoding='utf-8'))",
              "SLUGS = {p['id']: p['id'] + '/' for p in pages.values() if p['group'] in ('Темы', 'История философии', 'Личности')}")
s = s.replace("name = re.sub(r' [a-f0-9]{32}_all$', '', path.stem)", "name = path.stem.removesuffix('_all')")
s = s.replace("db_ids = {ID.search(p.name)[1]: re.sub(r' [a-f0-9]{32}_all$', '', p.stem)\n          for p in CONTENT.rglob('*_all.csv')}",
              "db_ids = {GROUP_KEY[p.stem.removesuffix('_all')]: p.stem.removesuffix('_all') for p in CONTENT.rglob('*_all.csv')}")
s = s.replace("    match = ID.search(decoded)", "    match = ID.search(decoded)")
s = s.replace("    pattern = re.compile(r'([^\\n]*?) \\(([^\\s]*?[a-f0-9]{32}\\.md)\\)(?:, |$)')",
              "    pattern = re.compile(r'([^\\n]*?) \\(((?:people|topics|history|quotes|articles)/[a-z0-9-]+\\.md)\\)(?:, |$)')")
s = s.replace("    pattern = re.compile(r'([^\\n]*?) \\(([^\\s]*?[a-f0-9]{32}\\.md)\\)(?:, |$)')",
              "    pattern = re.compile(r'([^\\n]*?) \\(((?:people|topics|history|quotes|articles)/[a-z0-9-]+\\.md)\\)(?:, |$)')")
s = s.replace("re.findall(r'([a-f0-9]{32})\\.md',", "re.findall(r'((?:people|topics|history|quotes|articles)/[a-z0-9-]+)\\.md',")
s = s.replace("if set(SLUGS) != public_ids:\n    raise ValueError('Public slug registry does not match the current published IDs. Update content/slugs.json.')",
              "if set(SLUGS) != public_ids:\n    raise ValueError('Public records must have canonical typed slugs.')")
s = s.replace("return 'index.html#quote-' + page['id']", "return 'index.html#quote-' + page['id'].split('/')[-1]")
s = s.replace("f' id=\"quote-{page[\"id\"]}\"'", "f' id=\"quote-{page[\"id\"].split(\"/\")[-1]}\"'")
s = s.replace("return SLUGS.get(page['id'], '#')", "return SLUGS.get(page['id'], '#')")
build.write_text(s)

audit = ROOT / "scripts/audit_content.py"
s = audit.read_text()
s = s.replace("STABLE_ID = re.compile(r'([a-f0-9]{32})\\.md$', re.I)",
              "STABLE_ID = re.compile(r'^([a-z0-9]+(?:-[a-z0-9]+)*)\\.md$', re.I)")
s = s.replace("REFERENCED_ID = re.compile(r'([a-f0-9]{32})\\.md', re.I)",
              "REFERENCED_ID = re.compile(r'((?:people|topics|history|quotes|articles)/[a-z0-9-]+)\\.md', re.I)")
s = s.replace("group = re.sub(r' [a-f0-9]{32}_all$', '', path.stem, flags=re.I)",
              "group = path.stem.removesuffix('_all')")
s = s.replace("    slugs_file = root / 'content' / 'slugs.json'\n    slugs = json.loads(slugs_file.read_text(encoding='utf-8')) if slugs_file.exists() else {}",
              "    group_keys = {'Темы': 'topics', 'Личности': 'people', 'История философии': 'history', 'Цитаты': 'quotes', 'Самостоятельная работа': 'articles'}")
s = s.replace("        match = STABLE_ID.search(path.name)", "        match = STABLE_ID.search(path.name)")
s = s.replace("        pid = match[1].lower()", "        section = path.parent.name if path.parent != content else '(root)'\n        pid = 'home' if section == '(root)' else group_keys[section] + '/' + match[1].lower()")
s = s.replace("home_url + slugs[pid] if pid in slugs else None", "home_url + pid + '/'")
s = s.replace("home_url + '#quote-' + pid", "home_url + '#quote-' + pid.split('/')[-1]")
audit.write_text(s)

for p in ["tests/test_site.py", "tests/test_public_content_consistency.py", "tests/test_quote_provenance.py", "tests/test_editorial_audit.py"]:
    path = ROOT / p
    s = path.read_text()
    for old, key in mapping.items():
        s = s.replace(old, key)
    s = s.replace("json.loads((ROOT / 'content/slugs.json').read_text())",
                  "{key: key + '/' for key in [*('topics/' + p.stem for p in (ROOT / 'content/knowledge/Философия/Темы').glob('*.md')), *('history/' + p.stem for p in (ROOT / 'content/knowledge/Философия/История философии').glob('*.md')), *('people/' + p.stem for p in (ROOT / 'content/knowledge/Философия/Личности').glob('*.md'))]}")
    s = s.replace("re.findall(r'([a-f0-9]{32})\\.md'", "re.findall(r'((?:people|topics|history|quotes|articles)/[a-z0-9-]+)\\.md'")
    s = s.replace("re.search(r'([a-f0-9]{32})\\.md$'", "re.search(r'([a-z0-9-]+)\\.md$'")
    s = s.replace("ID_RE = re.compile(r\"([a-f0-9]{32})\\.md$\")", "ID_RE = re.compile(r\"([a-z0-9-]+)\\.md$\")")
    path.write_text(s)

print(f"Migrated {len(files)} Markdown records and {len(mapping)} typed keys.")
