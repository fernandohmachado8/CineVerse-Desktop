"""Audit Git-tracked files before publication; report paths, never secret values."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
ALLOWED={'.py','.ps1','.rs','.toml','.lock','.json','.tsx','.ts','.html','.css','.svg','.md','.txt','.yml','.yaml'}
NAMES={'.gitignore','.gitattributes','LICENSE'}
PRIVATE={'portable.json','engine.json','settings.json','guard-config.json','gpu-config.json','smoke-request.json'}
PATTERNS=[r'[A-Z]:[/\\]Users[/\\]',r'F:[/\\]CineVerse',r'(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}',
          r'github_pat_[A-Za-z0-9_]{20,}',r'hf_[A-Za-z0-9]{25,}',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']


def audit():
    names=subprocess.check_output(['git','ls-files','--cached','-z'],cwd=ROOT).decode().split('\0')
    provenance=json.loads((ROOT/'docs/assets/provenance.json').read_text())['assets']
    issues=[];total=0;count=0
    for name in filter(None,names):
        file=ROOT/name;data=subprocess.check_output(['git','show',':'+name],cwd=ROOT);total+=len(data);count+=1
        if file.name in PRIVATE:issues.append({'path':name,'reason':'private settings'})
        if file.suffix in ('.gif','.png'):
            record=provenance.get(file.name)
            if name!='docs/assets/'+file.name or not record or hashlib.sha256(data).hexdigest()!=record['sha256']:
                issues.append({'path':name,'reason':'unregistered binary asset'})
            continue
        if file.suffix not in ALLOWED and file.name not in NAMES:issues.append({'path':name,'reason':'non-source type'})
        if len(data)>2_000_000:issues.append({'path':name,'reason':'large source file'})
        try:text=data.decode('utf8')
        except UnicodeDecodeError:issues.append({'path':name,'reason':'binary data'});continue
        if name=='scripts/audit_publication.py':continue
        for pattern in PATTERNS:
            if re.search(pattern,text,re.I):issues.append({'path':name,'reason':'private path or credential pattern'})
    return {'pass':not issues,'files':count,'bytes':total,'issues':issues}


if __name__=='__main__':
    result=audit();print(json.dumps(result,indent=2));raise SystemExit(0 if result['pass'] else 1)
