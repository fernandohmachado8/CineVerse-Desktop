"""Pinned Windows engine installation; never installs drivers or converts media."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / 'requirements/engine-manifest.json'
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def report(stage, message, **data):
    print(json.dumps(dict(type='progress',stage=stage,message=message,**data)),flush=True)


def digest(file):
    with Path(file).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def atomic_json(path, data):
    path=Path(path);temp=path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data,indent=2),encoding='utf8');temp.replace(path)


def long_path(path):
    value=str(Path(path).resolve())
    if os.name!='nt' or value.startswith('\\\\?\\'):return value
    return '\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value


def safe_extract(archive, destination):
    destination=Path(destination).resolve()
    with zipfile.ZipFile(archive) as source:
        if sum(i.file_size for i in source.infolist())>2*1024**3:raise ValueError('Archive exceeds the extraction budget.')
        for item in source.infolist():
            name=PurePosixPath(item.filename.replace('\\','/'))
            output=destination.joinpath(*name.parts).resolve()
            if name.is_absolute() or any(':' in p for p in name.parts) or not output.is_relative_to(destination):
                raise ValueError('Unsafe archive member: '+item.filename)
            if stat.S_ISLNK(item.external_attr>>16):raise ValueError('Archive symlinks are not accepted.')
        source.extractall(long_path(destination))


def verified_download(asset, file):
    file=Path(file)
    if file.is_file():
        if digest(file)!=asset['sha256']:raise ValueError('Existing download has a different SHA-256: '+str(file))
        return file
    file.parent.mkdir(parents=True,exist_ok=True);partial=file.with_suffix(file.suffix+'.part')
    request=urllib.request.Request(asset['url'],headers={'User-Agent':'CineVerse-Desktop-setup/0.6'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request,timeout=60) as response,partial.open('wb') as out:
                total=int(response.headers.get('Content-Length',0));done=0
                while block:=response.read(1024**2):
                    out.write(block);done+=len(block)
                    report('Downloading verified files',file.name,bytes=done,totalBytes=total or None,
                           percent=100*done/total if total else None)
            break
        except OSError as error:
            if attempt==2:raise ValueError('Download failed after three attempts: '+file.name+'. Check the connection and retry. '+str(error)) from error
            report('Retrying download',file.name+' (attempt '+str(attempt+2)+' of 3)')
            time.sleep(attempt+1)
    if digest(partial)!=asset['sha256']:raise ValueError('Downloaded file failed SHA-256 verification: '+str(partial))
    partial.replace(file);return file


def execute(args, **kwargs):
    print('> '+subprocess.list2cmdline(list(map(str,args))),flush=True)
    subprocess.run(list(map(str,args)),check=True,creationflags=FLAGS,**kwargs)


def checkout(asset, root):
    """Verified commit archives: no Git, compiler or system PATH required."""
    root=Path(root).resolve();destination=(root/asset['directory']).resolve()
    if not destination.is_relative_to(root):raise ValueError('Source destination escapes the engine folder.')
    receipt=destination/'.cineverse-source.json';expected={'commit':asset['commit'],'sha256':asset['archive']['sha256']}
    if destination.exists():
        if receipt.is_file() and json.loads(receipt.read_text(encoding='utf8'))==expected:return
        raise ValueError('Refusing to replace an existing or incomplete source folder: '+str(destination))
    archive=verified_download(asset['archive'],root/'downloads'/(asset['name']+'-'+asset['commit']+'.zip'))
    staging=root/'downloads'/('extract-'+uuid.uuid4().hex);staging.mkdir(parents=True)
    safe_extract(archive,staging)
    entries=list(staging.iterdir())
    if len(entries)!=1 or not entries[0].is_dir():raise ValueError('Unexpected commit archive layout.')
    if (entries[0]/'.gitmodules').is_file() and (entries[0]/'.gitmodules').read_text(encoding='utf8').strip():
        raise ValueError('This pinned source requires submodules; its manifest needs explicit archives.')
    atomic_json(entries[0]/'.cineverse-source.json',expected)
    destination.parent.mkdir(parents=True,exist_ok=True);entries[0].replace(destination);staging.rmdir()


def profile_manifest(manifest, profile):
    if profile=='cpu':return {**manifest,**manifest['cpuProfile']}
    return {**manifest,'processingBackend':'cuda'}


def plan(root, manifest, models=False):
    backend=manifest.get('processingBackend','cuda')
    return dict(root=str(root),platform=manifest['platform'],python=manifest['python'],
        repositories=[r for r in manifest['repositories'] if backend!='cpu' or r['name']!='rife'],
        torch=manifest['torch'],torchIndex=manifest['torchIndex'],archives=[manifest['ffmpeg'],manifest['sensor']],
        models=manifest['models']+([manifest['rifeModel']] if backend=='cuda' else []) if models else [],
        processingBackend=backend,driverInstalledAutomatically=False,startsConversion=False,
        note='Plan only unless --install is supplied. Review THIRD_PARTY_NOTICES.md before downloading.')


def select_profile(profile, ffmpeg):
    if profile!='auto':return profile
    args=[str(ffmpeg),'-v','error','-f','lavfi','-i','color=black:s=256x256:d=0.05',
          '-vf','format=p010le','-c:v','hevc_nvenc','-profile:v','main10','-f','null','-']
    try:
        result=subprocess.run(args,capture_output=True,creationflags=FLAGS,timeout=45)
        return 'cuda' if result.returncode==0 else 'cpu'
    except (OSError,subprocess.TimeoutExpired):return 'cpu'


def config_for(root, python, ffmpeg, backend, train_log):
    return dict(python=str(python),iw3Repo=str(root/'tools/nunif-iw3'),ffmpeg=str(ffmpeg),
        ffprobe=str(ffmpeg.with_name('ffprobe.exe')),cache=str(root/'iw3-trial/cache'),
        rifeRepo=str(root/'tools/Practical-RIFE'),rifeModel=str(train_log),
        sensorLibrary=str(root/'tools/thermal-guard/LibreHardwareMonitor'),
        cpuDriverInstaller=str(root/'downloads/PawnIO_setup.exe'),
        outputDir=str(root/'Movies'),thermalMode='required',backend=backend)


def claim_install_root(root, manifest):
    marker=root/'.cineverse-managed.json'
    expected=dict(schema=1,runtimeSha256=manifest['bootstrapPython']['sha256'])
    if marker.is_file():
        if json.loads(marker.read_text(encoding='utf8'))!=expected:raise ValueError('This engine folder belongs to another runtime version.')
    else:
        if root.exists() and any(root.iterdir()):raise ValueError('Choose a new empty engine folder; existing files are preserved.')
        root.mkdir(parents=True,exist_ok=True);atomic_json(marker,expected)


def install(root, manifest, models, rife_archive=None, resume=False, profile=None):
    if os.name!='nt' or sys.version_info[:2]!=(3,12):raise ValueError('Use Windows x64 CPython 3.12 for this tested engine profile.')
    root=Path(root).resolve()
    if (root/'engine.json').exists() and not resume:raise ValueError('This folder already has an engine. Use --check or choose a separate folder.')
    claim_install_root(root,manifest)
    if shutil.disk_usage(root).free<15*1024**3:raise ValueError('Allow at least 15 GiB for setup, excluding movie workspaces.')
    downloads=root/'downloads'
    temporary=root/'tmp';temporary.mkdir(exist_ok=True)
    os.environ.update(TEMP=str(temporary),TMP=str(temporary))
    report('Installing video tools','Downloading and checking FFmpeg and sensor files')
    ffmpeg_zip=verified_download(manifest['ffmpeg'],downloads/'ffmpeg-9.0.2.zip')
    safe_extract(ffmpeg_zip,root/'tools/ffmpeg')
    ffmpeg=next((root/'tools/ffmpeg').glob('*/bin/ffmpeg.exe'))
    backend=select_profile(profile or manifest.get('processingBackend','cuda'),ffmpeg)
    manifest=profile_manifest(manifest,backend)
    report('Choosing processing profile','Selected '+('NVIDIA CUDA' if backend=='cuda' else 'CPU compatibility'),backend=backend)
    sensor_zip=verified_download(manifest['sensor'],downloads/'LibreHardwareMonitor-0.9.6.zip')
    safe_extract(sensor_zip,root/'tools/thermal-guard/LibreHardwareMonitor')
    if 'cpuDriver' in manifest:verified_download(manifest['cpuDriver'],downloads/'PawnIO_setup.exe')
    env=root/('environments/desktop-v06-'+backend);python=env/'Scripts/python.exe'
    if not python.exists():execute([sys.executable,'-m','venv',env])
    requirements=REPO/'requirements/engine-win-py312.txt'
    receipt=env/'.packages-ready.json';expected=dict(torch=manifest['torch'],torchvision=manifest['torchvision'],requirements=digest(requirements))
    report('Installing AI packages','This may download several GB. No GPU driver is changed.')
    pip=[python,'-u','-m','pip','--isolated','--cache-dir',str(downloads/'pip-cache'),'--disable-pip-version-check']
    if not receipt.is_file() or json.loads(receipt.read_text(encoding='utf8'))!=expected:
        execute(pip+['install','--only-binary=:all:','torch=='+manifest['torch'],'torchvision=='+manifest['torchvision'],'--index-url',manifest['torchIndex']])
        execute(pip+['install','--only-binary=:all:','-r',requirements])
        execute(pip+['check']);atomic_json(receipt,expected)
    else:execute(pip+['check'])
    if profile=='auto' and backend=='cuda':
        probe=subprocess.run([python,'-c','import torch,sys;sys.exit(0 if torch.cuda.is_available() else 1)'],capture_output=True,creationflags=FLAGS,timeout=60)
        if probe.returncode:
            report('Choosing processing profile','The installed CUDA runtime could not initialize. Selecting CPU compatibility before conversion.')
            return install(root,manifest,models,rife_archive,True,'cpu')
    for asset in manifest['repositories']:
        if backend=='cpu' and asset['name']=='rife':continue
        report('Installing engine code',asset['name']);checkout(asset,root)
    cache=root/'iw3-trial/cache';cache.mkdir(parents=True,exist_ok=True)
    model_root=root/'iw3-trial/rife-model';model_root.mkdir(parents=True,exist_ok=True)
    if models:
        report('Installing depth and filling models','Downloading original pinned model files')
        for asset in manifest['models']:verified_download(asset,cache/'iw3/pretrained_models/hub/checkpoints'/asset['name'])
    warnings=[]
    if models and backend=='cuda':
        try:
            report('Installing optional 60 FPS smoothing','Checking the official RIFE 4.25 model')
            archive=Path(rife_archive) if rife_archive else downloads/'rife425.zip'
            if rife_archive and not archive.is_file():raise ValueError('The supplied RIFE archive does not exist.')
            if not archive.exists():execute([python,'-m','gdown',manifest['rifeModel']['url'],'-O',archive])
            if digest(archive)!=manifest['rifeModel']['sha256']:raise ValueError('RIFE archive SHA-256 differs.')
            safe_extract(archive,model_root)
        except (OSError,ValueError,subprocess.SubprocessError,zipfile.BadZipFile) as error:
            warnings.append('60 FPS smoothing was not installed: '+str(error)+'. Original FPS remains available. Retry setup to add it.')
    weights=list(model_root.rglob('flownet.pkl'));train_log=weights[0].parent if weights else model_root/'train_log'
    if weights and digest(weights[0])!=manifest['rifeModel']['weightSha256']:raise ValueError('Extracted RIFE weights failed verification.')
    config=config_for(root,python,ffmpeg,backend,train_log)
    report('Checking installed engine','Testing imports and the selected encoder; no movie is processed')
    execute([python,'-u',REPO/'worker/worker.py','check'],input=json.dumps({'config':config}),text=True,timeout=120)
    # Publish only after checks succeed. An interrupted setup remains retryable.
    atomic_json(root/'engine.json',config)
    atomic_json(root/'setup-result.json',dict(ready=True,backend=backend,warnings=warnings,startsConversion=False))
    print(json.dumps(dict(type='installed',config=config,warnings=warnings)),flush=True)
    return config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=['auto','cuda','cpu'],default='cuda')
    parser.add_argument('--root',type=Path,required=True,help='Separate engine directory, e.g. D:/CineVerse')
    group=parser.add_mutually_exclusive_group();group.add_argument('--install',action='store_true');group.add_argument('--check',action='store_true')
    parser.add_argument('--resume',action='store_true',help='Retry/recheck this managed installation without replacing source folders')
    parser.add_argument('--download-models',action='store_true');parser.add_argument('--rife-archive',type=Path)
    args=parser.parse_args();root=args.root.expanduser().resolve()
    if args.rife_archive and not args.download_models:raise ValueError('--rife-archive requires --download-models.')
    manifest=json.loads(MANIFEST.read_text(encoding='utf8'))
    if root==REPO or root.is_relative_to(REPO):raise ValueError('Keep the engine outside the source repository.')
    if args.check:
        config=json.loads((root/'engine.json').read_text(encoding='utf-8-sig'))
        execute([config['python'],'-u',REPO/'worker/worker.py','check'],input=json.dumps({'config':config}),text=True,timeout=120)
    elif args.install:install(root,manifest,args.download_models,args.rife_archive,args.resume,args.profile)
    else:print(json.dumps(plan(root,profile_manifest(manifest,args.profile),args.download_models),indent=2))


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError,StopIteration,zipfile.BadZipFile) as error:
        print('Setup stopped: '+str(error),file=sys.stderr);sys.exit(1)
