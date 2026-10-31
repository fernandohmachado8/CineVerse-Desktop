"""Link a separately prepared official ROCm Python without replacing a CPU engine.

No package/driver installation or conversion. Native protection must still arm.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def linked_config(base,python,root):
    config=dict(base,python=str(python),backend='rocm',thermalMode='required',outputDir=str(root/'Movies'))
    for key in ('gpuUuid','gpuBinding','resolvedBackend','cpuSensorFile','lastVideo'):config.pop(key,None)
    return config


def link(base_file,root):
    base_file=base_file.expanduser().resolve();root=root.expanduser().resolve()
    if root==ROOT or root.is_relative_to(ROOT) or root==base_file.parent:
        raise ValueError('Choose a separate new engine folder outside the source tree and existing engine.')
    if root.exists() and any(root.iterdir()):raise ValueError('The destination must be empty. Existing engines are preserved.')
    config=linked_config(json.loads(base_file.read_text(encoding='utf-8-sig')),Path(sys.executable),root)
    result=subprocess.run([sys.executable,'-u',str(ROOT/'worker/worker.py'),'check'],
        input=json.dumps(dict(config=config)),text=True,encoding='utf8',capture_output=True,timeout=120,
        env=dict(os.environ,PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1'))
    if result.returncode:raise ValueError('The separate ROCm engine did not pass its check. '+result.stderr[-1800:])
    info=json.loads(result.stdout)
    if info.get('backend')!='rocm' or not info.get('ready'):raise ValueError('The check did not confirm a ROCm runtime.')
    root.mkdir(parents=True,exist_ok=True)
    temp=root/'engine.json.tmp';temp.write_text(json.dumps(config,indent=2),encoding='utf8');temp.replace(root/'engine.json')
    print(json.dumps(dict(ready=True,backend='rocm',experimental=True,startsConversion=False,
        engineFile=str(root/'engine.json'),note='CPU/FFmpeg/model assets are referenced read-only from the existing engine. GPU inference and temperature binding still need a real AMD test.')),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-engine',type=Path,required=True,help='Existing CPU engine.json; never changed')
    parser.add_argument('--root',type=Path,required=True,help='New empty folder for the experimental Radeon manifest')
    args=parser.parse_args()
    try:link(args.base_engine,args.root)
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('ROCm engine was not linked: '+str(error),file=sys.stderr);sys.exit(1)
