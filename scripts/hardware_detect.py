"""Read-only Windows inventory and conservative, reproducible engine selection."""
import json
import os
from pathlib import Path
import platform
import re
import subprocess

FLAGS=getattr(subprocess,'CREATE_NO_WINDOW',0)


def inventory():
    if os.name!='nt':return dict(state='unavailable',architecture=platform.machine(),gpus=[],message='Windows inventory is unavailable on this platform.')
    powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result=subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-File',str(Path(__file__).with_name('hardware_probe.ps1'))],
            capture_output=True,text=True,encoding='utf-8-sig',errors='replace',timeout=30,creationflags=FLAGS,check=True)
        data=json.loads(result.stdout)
        if not isinstance(data,dict) or not isinstance(data.get('gpus'),list):raise ValueError('Invalid hardware inventory')
        return data
    except (OSError,ValueError,subprocess.SubprocessError):
        return dict(state='unavailable',architecture='x64' if platform.machine().upper() in ('AMD64','X86_64') else 'unsupported',gpus=[],
            message='Windows hardware inventory could not be read. Automatic setup will use CPU compatibility.')


def model_name(value):
    value=re.sub(r'\((?:tm|r)\)','',str(value).lower())
    return re.sub(r'[^a-z0-9]','',value).removeprefix('amd')


def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d+(?:\.\d+){3}',value):return None
    return tuple(map(int,value.split('.')))


def choose(data,recipe,nvidia_ready=False):
    """Only allowlisted AMD models may attempt installation; a live probe follows."""
    if data.get('architecture')=='unsupported':raise ValueError('This Windows installer requires an Intel/AMD x64 processor; Windows ARM is not supported.')
    if data.get('state')!='detected':return dict(backend='cpu',reason=data.get('message','GPU detection unavailable; using CPU compatibility.'))
    if data.get('architecture')!='x64':raise ValueError('This Windows installer requires an Intel/AMD x64 processor; Windows ARM is not supported.')
    gpus=data.get('gpus',[])
    if nvidia_ready and any(g.get('vendorId')=='10DE' and g.get('healthy') is True for g in gpus):
        return dict(backend='cuda',reason='NVIDIA hardware and its Main10 encoder passed detection.')
    amd=[g for g in gpus if g.get('vendorId')=='1002']
    if not amd:return dict(backend='cpu',reason='No compatible accelerated engine was detected. CPU compatibility will be installed.')
    if len(amd)!=1:return dict(backend='cpu',reason='Multiple AMD adapters require hardware validation; CPU compatibility will be installed.')
    gpu=amd[0]
    if not gpu.get('healthy'):return dict(backend='cpu',reason='The AMD adapter is unavailable or disabled. CPU compatibility will be installed.')
    if not data.get('desktop') or data.get('windowsBuild',0)<recipe['minimumWindowsBuild']:
        return dict(backend='cpu',reason='The pinned AMD runtime requires supported Windows 11 desktop. CPU compatibility will be installed.')
    match=next((m for m in recipe['supportedModels'] if model_name(m['name'])==model_name(gpu.get('name'))),None)
    if match is None:return dict(backend='cpu',reason='This AMD model is outside the pinned GPU recipe. CPU compatibility will be installed.')
    driver=version(gpu.get('driverVersion'))
    if driver is None or driver<version(recipe['minimumDriverStoreVersion']):
        return dict(backend='cpu',reason='The AMD graphics driver needs an update for this GPU recipe. CPU compatibility will be installed; no driver is changed.')
    return dict(backend='rocm',reason='AMD model, Windows and driver checks passed. Installing the pinned experimental AMD runtime for a live startup check.',
        gpuName=gpu['name'],architecture=match['architecture'],driverVersion=gpu['driverVersion'])
