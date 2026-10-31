"""macOS Apple Silicon engine provisioning. Never changes Gatekeeper or drivers."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from setup_engine import (REPO, MANIFEST, atomic_json, digest, verified_download,
    checkout, claim_install_root, execute, report)


def mac_manifest(base):
    mac=base['macosArm64']
    return {**base,**mac,'processingBackend':'cpu'}


def ensure_macos_arm64():
    if sys.platform!='darwin' or platform.machine()!='arm64':
        raise ValueError('This preview requires native Apple Silicon macOS, not Intel or Rosetta Python.')
    if tuple(map(int,platform.mac_ver()[0].split('.')[:2]))<(14,0):
        raise ValueError('This preview requires macOS 14 or later.')
    if sys.version_info[:2]!=(3,12):raise ValueError('The private Python 3.12 runtime is required.')


def install(root, profile):
    ensure_macos_arm64()
    if profile not in ('auto','cpu','mps'):raise ValueError('Choose Automatic, CPU or experimental Apple MPS.')
    manifest=mac_manifest(json.loads(MANIFEST.read_text(encoding='utf8')))
    claim_install_root(root,manifest)
    if shutil.disk_usage(root).free<8*1024**3:raise ValueError('Allow at least 8 GiB free for the Mac engine.')
    temporary=root/'tmp';temporary.mkdir(exist_ok=True)
    os.environ.update(TMPDIR=str(temporary),TEMP=str(temporary),TMP=str(temporary),PYTHONUNBUFFERED='1')
    downloads=root/'downloads';tools=root/'tools/ffmpeg';tools.mkdir(parents=True,exist_ok=True)
    report('Installing Mac video tools','Verifying static arm64 FFmpeg and FFprobe; no Homebrew required')
    for asset in manifest['ffmpegAssets']:
        source=verified_download(asset,downloads/('macos-'+asset['name']))
        target=tools/asset['name'];receipt=target.with_name(target.name+'.receipt.json')
        if receipt.is_file():
            record=json.loads(receipt.read_text(encoding='utf8'))
            if record.get('sourceSha256')==asset['sha256'] and target.is_file() and record.get('installedSha256')==digest(target):continue
        shutil.copyfile(source,target)
        if asset['name'] in ('ffmpeg','ffprobe'):
            target.chmod(0o755)
            # Preserve an existing signature; otherwise sign the checked copy ad-hoc.
            # This does not notarize it or remove quarantine/security attributes.
            valid=subprocess.run(['/usr/bin/codesign','--verify',str(target)],capture_output=True)
            if valid.returncode:execute(['/usr/bin/codesign','--sign','-',str(target)])
        atomic_json(receipt,dict(sourceSha256=asset['sha256'],installedSha256=digest(target)))
    env=root/'environments/desktop-v07-macos';python=env/'bin/python3'
    if not python.is_file():execute([sys.executable,'-m','venv',str(env)])
    requirements=REPO/'requirements/engine-macos-py312.txt'
    expected=dict(torch=manifest['torch'],torchvision=manifest['torchvision'],requirements=digest(requirements))
    receipt=env/'.packages-ready.json';pip=[str(python),'-u','-m','pip','--isolated','--cache-dir',str(downloads/'pip-cache'),'--disable-pip-version-check']
    report('Installing Mac AI packages','Installing pinned native arm64 wheels')
    if not receipt.is_file() or json.loads(receipt.read_text(encoding='utf8'))!=expected:
        execute(pip+['install','--only-binary=:all:','torch=='+manifest['torch'],'torchvision=='+manifest['torchvision'],'--index-url',manifest['torchIndex']])
        execute(pip+['install','--only-binary=:all:','-r',str(requirements)])
        execute(pip+['check']);atomic_json(receipt,expected)
    else:execute(pip+['check'])
    for asset in manifest['repositories']:
        if asset['name']=='rife':continue
        report('Installing Mac engine code',asset['name']);checkout(asset,root)
    cache=root/'iw3-trial/cache'
    report('Installing depth and filling models','Verifying the original model weights')
    for asset in manifest['models']:
        verified_download(asset,cache/'iw3/pretrained_models/hub/checkpoints'/asset['name'])
    backend='mps' if profile=='mps' else 'cpu'
    config=dict(python=str(python),iw3Repo=str(root/'tools/nunif-iw3'),ffmpeg=str(tools/'ffmpeg'),ffprobe=str(tools/'ffprobe'),
        cache=str(cache),rifeRepo='',rifeModel='',sensorLibrary='',cpuDriverInstaller='',outputDir=str(root/'Movies'),
        thermalMode='macos',backend=backend,platform='macos')
    report('Checking Mac engine','Checking software encoding and the requested backend; no conversion')
    execute([str(python),'-u',str(REPO/'worker/worker.py'),'check'],input=json.dumps(dict(config=config)),text=True,timeout=120)
    atomic_json(root/'engine.json',config)
    warnings=['MPS inference is experimental and uses per-operation CPU fallback.'] if backend=='mps' else []
    atomic_json(root/'setup-result.json',dict(ready=True,backend=backend,warnings=warnings,startsConversion=False))
    print(json.dumps(dict(type='installed',config=config,warnings=warnings)),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--profile',choices=['auto','cpu','mps'],default='auto')
    parser.add_argument('--install',action='store_true');parser.add_argument('--resume',action='store_true');parser.add_argument('--download-models',action='store_true')
    args=parser.parse_args();root=args.root.expanduser().resolve()
    if root==REPO or root.is_relative_to(REPO):raise ValueError('Keep the engine outside the source tree.')
    if not args.install:raise ValueError('Use the app setup button or supply --install.')
    sys.path.insert(0,str(REPO/'worker'))
    from macos_platform import watch_parent
    watch_parent();install(root,args.profile)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('Mac setup stopped: '+str(error),file=sys.stderr);sys.exit(1)
