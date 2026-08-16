from pathlib import Path
import ast, subprocess, sys, os

ROOT=Path(__file__).resolve().parent
REQUIRED=['app.py','README.md','requirements.txt','requirements-lock.txt','tests/test_production.py','qa_live.py']
missing=[p for p in REQUIRED if not (ROOT/p).exists()]
if missing: raise SystemExit(f'Missing release files: {missing}')
bad=[]
for p in ROOT.rglob('*'):
    if p.is_dir() and p.name=='__pycache__': bad.append(str(p))
    if p.is_file() and p.suffix=='.pyc': bad.append(str(p))
if bad: raise SystemExit(f'Generated artifacts found: {bad}')
src=(ROOT/'app.py').read_text(encoding='utf-8'); tree=ast.parse(src)
version=None
for n in tree.body:
    if isinstance(n,ast.Assign):
        for t in n.targets:
            if isinstance(t,ast.Name) and t.id=='VERSION': version=ast.literal_eval(n.value)
if version!='V22.0 QA/PRODUCTION': raise SystemExit(f'Unexpected VERSION: {version}')
for name in REQUIRED:
    if name.endswith('.py'): ast.parse((ROOT/name).read_text(encoding='utf-8'))
env=os.environ.copy(); env['PYTHONDONTWRITEBYTECODE']='1'; env.pop('EGX_LIVE_SMOKE',None)
p=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests','-v'],cwd=ROOT,env=env)
if p.returncode: raise SystemExit(p.returncode)
print('RELEASE QA: PASS'); print('Version:',version)
if os.getenv('EGX_LIVE_SMOKE','0')=='1':
    p2=subprocess.run([sys.executable,'qa_live.py',os.getenv('EGX_LIVE_SYMBOL','COMI')],cwd=ROOT,env=env)
    if p2.returncode: raise SystemExit(p2.returncode)
    print('LIVE YAHOO GATE: PASS')
else:
    print('LIVE YAHOO GATE: SKIPPED (set EGX_LIVE_SMOKE=1 for real external test)')
