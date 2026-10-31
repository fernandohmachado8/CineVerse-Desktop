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
sys.path.insert(0,str(Path(__file__).resolve().parent))
from hardware_detect import inventory,choose,model_name

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / 'requirements/engine-manifest.json'
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class IntegrityError(ValueError):pass
class StartupError(ValueError):pass
class DownloadError(ValueError):pass


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
        if digest(file)!=asset['sha256']:raise IntegrityError('Existing download has a different SHA-256: '+str(file))
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
            if attempt==2:raise DownloadError('Download failed after three attempts: '+file.name+'. Check the connection and retry. '+str(error)) from error
            report('Retrying download',file.name+' (attempt '+str(attempt+2)+' of 3)')
            time.sleep(attempt+1)
    if digest(partial)!=asset['sha256']:raise IntegrityError('Downloaded file failed SHA-256 verification: '+str(partial))
    partial.replace(file);return file


def execute(args, **kwargs):
    print('> '+subprocess.list2cmdline(list(map(str,args))),flush=True)
    if kwargs:
        subprocess.run(list(map(str,args)),check=True,creationflags=FLAGS,**kwargs)
        return
    # Explicit pipes preserve package diagnostics even without a console window.
    with subprocess.Popen(list(map(str,args)),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,encoding='utf8',errors='replace',creationflags=FLAGS) as child:
        tail=[]
        for line in child.stdout:
            print(line.rstrip(),flush=True);tail.append(line.rstrip());tail=tail[-12:]
        if child.wait():raise subprocess.CalledProcessError(child.returncode,args,output='\n'.join(tail))


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
    if profile=='rocm':return {**manifest,**manifest['rocmProfile']}
    return {**manifest,'processingBackend':'cuda'}


def plan(root, manifest, models=False):
    backend=manifest.get('processingBackend','cuda')
    return dict(root=str(root),platform=manifest['platform'],python=manifest['python'],
        repositories=[r for r in manifest['repositories'] if backend=='cuda' or r['name']!='rife'],
        torch=manifest['torch'],torchIndex=manifest['torchIndex'],archives=[manifest['ffmpeg'],manifest['sensor']],
        models=manifest['models']+([manifest['rifeModel']] if backend=='cuda' else []) if models else [],
        processingBackend=backend,driverInstalledAutomatically=False,startsConversion=False,
        note='Plan only unless --install is supplied. Review THIRD_PARTY_NOTICES.md before downloading.')


def selection(profile,ffmpeg,manifest,data=None):
    data=inventory() if data is None else data
    if data.get('architecture')=='unsupported':raise ValueError('This installer requires an Intel/AMD x64 CPU; Windows ARM is not supported.')
    if profile=='cpu':return dict(backend='cpu',reason='CPU compatibility selected.'),data
    if profile=='cuda':return dict(backend='cuda',reason='NVIDIA processing explicitly selected.'),data
    ready=False
    if any(g.get('vendorId')=='10DE' and g.get('healthy') is True for g in data.get('gpus',[])):
        ready=select_profile('auto',ffmpeg)=='cuda'
    decision=choose(data,manifest['rocmProfile'],nvidia_ready=ready)
    if profile=='rocm' and decision['backend']!='rocm':raise ValueError(decision['reason']+' Select Automatic for a supported fallback.')
    return decision,data


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


def prepare_packages(root,base,backend):
    manifest=profile_manifest(base,backend)
    # ROCm contains long kernel filenames. Keep managed venv paths short rather
    # than changing Windows long-path/security policy on another user's PC.
    env=root/'env'/backend;python=env/'Scripts/python.exe'
    if not python.exists():execute([sys.executable,'-m','venv',env])
    requirements=REPO/'requirements/engine-win-py312.txt'
    expected=dict(torch=manifest['torch'],torchvision=manifest['torchvision'],requirements=digest(requirements),
        amdAssets=[a['sha256'] for a in manifest['assets']] if backend=='rocm' else [])
    receipt=env/'.packages-ready.json'
    pip=[python,'-u','-m','pip','--isolated','--cache-dir',str(root/'downloads/pip-cache'),'--disable-pip-version-check']
    if not receipt.is_file() or json.loads(receipt.read_text(encoding='utf8'))!=expected:
        if backend=='rocm':
            report('Installing AMD dependencies','Downloading and verifying the pinned official ROCm recipe; no graphics driver is changed.')
            files=[verified_download(a,root/'downloads/amd'/a['name']) for a in manifest['assets']]
            check_wheel_paths(files,env)
            execute(pip+['install','--only-binary=:all:',*manifest['buildTools'],'--index-url','https://pypi.org/simple'])
            execute(pip+['install','--no-deps','--no-build-isolation',*files])
        else:
            execute(pip+['install','--only-binary=:all:','torch=='+manifest['torch'],'torchvision=='+manifest['torchvision'],'--index-url',manifest['torchIndex']])
        execute(pip+['install','--only-binary=:all:','-r',requirements,'--index-url','https://pypi.org/simple'])
        execute(pip+['check']);atomic_json(receipt,expected)
    else:execute(pip+['check'])
    return python


def check_wheel_paths(files,env):
    for file in files:
        if Path(file).suffix!='.whl':continue
        with zipfile.ZipFile(file) as archive:
            if any(len(str(env/'Lib/site-packages'/name))>=260 for name in archive.namelist()):
                raise StartupError('The AMD package contains long filenames. Choose a shorter engine location, such as D:/CineVerse, or use Automatic for CPU fallback. No Windows policy was changed.')


def runtime_check(python,backend,repo=None):
    command=[str(python),'-u',str(REPO/'scripts/runtime_probe.py'),'--backend',backend]
    if repo:command+=['--iw3-repo',str(repo)]
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=120,creationflags=FLAGS)
    try:data=json.loads(result.stdout)
    except ValueError:data={}
    if result.returncode or not data.get('ready'):
        raise StartupError(data.get('error') or ('Runtime startup failed: '+result.stderr[-1200:]))
    return data


def choose_working_backend(requested,backend,prepare,validate,warnings):
    """A failed GPU startup in Automatic installs CPU; integrity failures stop."""
    try:
        python=prepare(backend);proof=validate(python,backend)
        return backend,python,proof
    except (subprocess.SubprocessError,StartupError,DownloadError,OSError) as error:
        if requested!='auto' or backend not in ('cuda','rocm'):raise
        detail=getattr(error,'output',None) or str(error)
        warning=('AMD' if backend=='rocm' else 'NVIDIA')+' startup failed. Switching to CPU compatibility automatically. '+str(detail)[-1000:]
        report('Selecting CPU fallback',warning);warnings.append(warning)
        python=prepare('cpu');proof=validate(python,'cpu')
        return 'cpu',python,proof


def install(root, manifest, models, rife_archive=None, resume=False, profile=None):
    if os.name!='nt' or sys.version_info[:2]!=(3,12):raise ValueError('Use Windows x64 CPython 3.12 for this engine profile.')
    root=Path(root).resolve();base=manifest;requested=profile or 'auto'
    if (root/'engine.json').exists() and not resume:raise ValueError('This folder already has an engine. Use --check or choose a separate folder.')
    claim_install_root(root,base)
    if shutil.disk_usage(root).free<15*1024**3:raise ValueError('Allow at least 15 GiB for setup, excluding video workspaces.')
    downloads=root/'downloads';temporary=root/'tmp';temporary.mkdir(exist_ok=True)
    os.environ.update(TEMP=str(temporary),TMP=str(temporary),PYTHONUNBUFFERED='1',PYTHONDONTWRITEBYTECODE='1')
    report('Detecting CPU and GPUs','Reading Windows hardware, architecture and installed driver information.')
    data=inventory()
    atomic_json(root/'hardware-detection.json',data)
    report('Installing video tools','Downloading and checking FFmpeg and sensor files')
    ffmpeg_zip=verified_download(base['ffmpeg'],downloads/'ffmpeg-9.0.2.zip')
    safe_extract(ffmpeg_zip,root/'tools/ffmpeg')
    ffmpeg=next((root/'tools/ffmpeg').glob('*/bin/ffmpeg.exe'))
    decision,data=selection(requested,ffmpeg,base,data)
    backend=decision['backend'];warnings=[]
    if backend=='rocm' and shutil.disk_usage(root).free<base['rocmProfile']['minimumFreeGiB']*1024**3:
        if requested!='auto':raise ValueError('Allow at least 25 GiB free for AMD setup and fallback. Choose another engine location.')
        backend='cpu';decision=dict(backend='cpu',reason='AMD setup needs at least 25 GiB free. CPU compatibility will be installed automatically.')
    report('Choosing processing package',decision['reason'],backend=backend)
    if backend=='cpu' and any(g.get('vendorId') in ('1002','10DE') for g in data.get('gpus',[])):warnings.append(decision['reason'])
    sensor_zip=verified_download(base['sensor'],downloads/'LibreHardwareMonitor-0.9.6.zip')
    safe_extract(sensor_zip,root/'tools/thermal-guard/LibreHardwareMonitor')
    if 'cpuDriver' in base:verified_download(base['cpuDriver'],downloads/'PawnIO_setup.exe')
    for asset in base['repositories']:
        if backend!='cuda' and asset['name']=='rife':continue
        report('Installing engine code',asset['name']);checkout(asset,root)
    cache=root/'iw3-trial/cache';cache.mkdir(parents=True,exist_ok=True)
    model_root=root/'iw3-trial/rife-model';model_root.mkdir(parents=True,exist_ok=True)
    if models:
        report('Installing depth and filling models','Downloading original pinned model files')
        for asset in base['models']:verified_download(asset,cache/'iw3/pretrained_models/hub/checkpoints'/asset['name'])
    def validate(python,candidate):
        report('Checking installed runtime','Testing imports and tiny inference operations; no video conversion.',backend=candidate)
        proof=runtime_check(python,candidate,root/'tools/nunif-iw3')
        if candidate=='rocm':
            if model_name(proof.get('gpuName'))!=model_name(decision.get('gpuName')) or proof.get('architecture')!=decision.get('architecture'):
                raise StartupError('The initialized AMD device does not match the detected, allowlisted GPU.')
        config=config_for(root,python,ffmpeg,candidate,model_root/'train_log')
        result=subprocess.run([str(python),'-u',str(REPO/'worker/worker.py'),'check'],input=json.dumps(dict(config=config)),
            capture_output=True,text=True,encoding='utf8',errors='replace',timeout=120,creationflags=FLAGS)
        if result.returncode:raise StartupError('Engine startup check failed. '+result.stderr[-1200:])
        return proof
    backend,python,proof=choose_working_backend(requested,backend,lambda b:prepare_packages(root,base,b),validate,warnings)
    if models and backend=='cuda':
        try:
            report('Installing optional 60 FPS smoothing','Checking the official RIFE 4.25 model')
            archive=Path(rife_archive) if rife_archive else downloads/'rife425.zip'
            if rife_archive and not archive.is_file():raise ValueError('The supplied RIFE archive does not exist.')
            if not archive.exists():execute([python,'-m','gdown',base['rifeModel']['url'],'-O',archive])
            if digest(archive)!=base['rifeModel']['sha256']:raise IntegrityError('RIFE archive SHA-256 differs.')
            safe_extract(archive,model_root)
        except IntegrityError:raise
        except (OSError,ValueError,subprocess.SubprocessError,zipfile.BadZipFile) as error:
            warnings.append('60 FPS smoothing was not installed: '+str(error)+'. Original FPS remains available. Retry setup to add it.')
    weights=list(model_root.rglob('flownet.pkl'));train_log=weights[0].parent if weights else model_root/'train_log'
    if weights and digest(weights[0])!=base['rifeModel']['weightSha256']:raise IntegrityError('Extracted RIFE weights failed verification.')
    config=config_for(root,python,ffmpeg,backend,train_log)
    config.update(managedBackend=backend,runtimeProbePassed=True,setupTorchVersion=proof['torch'])
    if backend=='rocm':
        config.update(setupGpuName=proof['gpuName'],setupRecipeVersion=base['rocmProfile']['runtimeVersion'])
        warnings.append('AMD startup checks passed locally. Radeon conversion quality and sustained sensor behavior remain experimental; start with a short preview.')
    if requested=='auto':config['backend']='auto'
    atomic_json(root/'runtime-check.json',proof)
    atomic_json(root/'hardware-selection.json',dict(requested=requested,decision=decision,selectedBackend=backend,warnings=warnings))
    # Publish only after package, import, tiny-runtime and encoder checks pass.
    atomic_json(root/'engine.json',config)
    atomic_json(root/'setup-result.json',dict(ready=True,backend=backend,warnings=warnings,startsConversion=False))
    print(json.dumps(dict(type='installed',config=config,warnings=warnings)),flush=True)
    return config


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=['auto','cuda','cpu','rocm'],default='auto')
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
    else:
        value=plan(root,profile_manifest(manifest,args.profile),args.download_models)
        if args.profile=='auto':value.update(processingBackend='auto',torch='Chosen after CPU/GPU/driver and runtime checks',note='Plan only. Automatic selects NVIDIA, allowlisted AMD or CPU after local checks; no downloads or conversion started.')
        print(json.dumps(value,indent=2))


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError,StopIteration,zipfile.BadZipFile) as error:
        print('Setup stopped: '+str(error),file=sys.stderr);sys.exit(1)
