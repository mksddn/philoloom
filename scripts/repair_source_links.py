from pathlib import Path
import json, re, subprocess
root=Path(__file__).resolve().parents[1]
def old(path):
    return subprocess.check_output(['git','show','origin/main:'+path], text=True)
mapping={k:v.rstrip('/') for k,v in json.loads(old('content/slugs.json')).items()}
old_quotes=json.loads(old('content/quote-provenance.json'))['quotes']
new_quotes=json.loads((root/'content/quote-provenance.json').read_text())['quotes']
assert len(old_quotes)==len(new_quotes)
mapping.update(zip(old_quotes,new_quotes))
old_names=subprocess.check_output(['git','ls-tree','-r','--name-only','origin/main','content/knowledge'],text=True).splitlines()
new_names=[p for p in (root/'content/knowledge').rglob('*.md')]
for p in old_names:
    if not p.endswith('.md'):continue
    m=re.search(r'([a-f0-9]{32})\.md$',p)
    if not m or m.group(1) in mapping:continue
    name=Path(p).name[:m.start()].rstrip()
    import unicodedata
    trans=dict(zip('абвгдежзийклмнопрстуфхцчшщъыьэюя',['a','b','v','g','d','e','zh','z','i','i','k','l','m','n','o','p','r','s','t','u','f','h','ts','ch','sh','shch','','y','','e','yu','ya']))
    stem=''.join(trans.get(c,c) for c in name.lower().replace('ё','е'))
    stem=re.sub('[^a-z0-9]+','-',stem).strip('-')[:85].strip('-') or 'entry'
    group=Path(p).parent.name
    kind={'Самостоятельная работа':'articles'}.get(group,'home')
    if kind=='home':mapping[m.group(1)]='home'
    else:
        options=[q for q in new_names if q.parent.name==group and q.stem.startswith(stem)]
        if len(options)==1:mapping[m.group(1)]=kind+'/'+options[0].stem
pattern=re.compile(r'(?:\.\./)?[\w.%/()-]*?([a-f0-9]{32})\.md')
counts={}
for path in (root/'content/knowledge').rglob('*'):
    if path.suffix not in ('.md','.csv'):continue
    text=path.read_text(encoding='utf-8-sig' if path.suffix=='.csv' else 'utf-8')
    def sub(m):
        key=mapping.get(m.group(1))
        if not key:return m.group(0)
        counts[key]=counts.get(key,0)+1
        prefix=re.match(r'^\(+',m.group(0))
        return (prefix.group(0) if prefix else '')+key+'.md'
    new=pattern.sub(sub,text)
    if 'Самостоятельная работа' in str(path):
        new=re.sub(r' [a-f0-9]{32}(?=\.md)', '', new)
    if path.name=='index.md':
        new=re.sub(r' [a-f0-9]{32}(?=(?:_all)?\.csv)', '', new)
    if new!=text:path.write_text(new,encoding='utf-8-sig' if path.suffix=='.csv' else 'utf-8')
remaining=[]
for path in (root/'content/knowledge').rglob('*'):
    if path.suffix in ('.md','.csv'):
        text=path.read_text(encoding='utf-8-sig' if path.suffix=='.csv' else 'utf-8')
        if re.search(r'[a-f0-9]{32}\.md',text):remaining.append(str(path))
print('Fixed links:',sum(counts.values()),'unconverted files:',remaining)
if remaining:raise SystemExit('Unconverted legacy links')
