"""Plan or install the pinned Windows engine outside this source repository.

No conversion, elevation, driver installation or security-policy changes occur.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / 'requirements/engine-manifest.json'
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def digest(file):
    with Path(file).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_extract(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as source:
        if sum(i.file_size for i in source.infolist()) > 2 * 1024**3:
            raise ValueError('Archive exceeds the extraction budget.')
        for item in source.infolist():
            name = PurePosixPath(item.filename.replace('\\', '/'))
            output = destination.joinpath(*name.parts).resolve()
            if name.is_absolute() or any(':' in p for p in name.parts) or not output.is_relative_to(destination):
                raise ValueError('Unsafe archive member: ' + item.filename)
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('Archive symlinks are not accepted.')
        source.extractall(destination)


def verified_download(asset, file):
    file = Path(file)
    if file.is_file():
        if digest(file) != asset['sha256']: raise ValueError('Existing download has a different SHA-256: ' + str(file))
        return file
    file.parent.mkdir(parents=True, exist_ok=True)
    partial = file.with_suffix(file.suffix + '.part')
    request = urllib.request.Request(asset['url'], headers={'User-Agent': 'CineVerse-Desktop-setup/0.5'})
    with urllib.request.urlopen(request, timeout=60) as response, partial.open('wb') as out:
        shutil.copyfileobj(response, out)
    if digest(partial) != asset['sha256']:
        raise ValueError('Downloaded file failed SHA-256 verification: ' + str(partial))
    partial.replace(file)
    return file


def execute(args, **kwargs):
    print('>', subprocess.list2cmdline(list(map(str, args))), flush=True)
    subprocess.run(list(map(str, args)), check=True, creationflags=FLAGS, **kwargs)


def checkout(asset, root):
    destination = root / asset['directory']
    if destination.exists():
        if not (destination / '.git').exists(): raise ValueError('Refusing to replace an existing folder: ' + str(destination))
        sha = subprocess.check_output(['git', '-C', str(destination), 'rev-parse', 'HEAD'], text=True).strip()
        if sha != asset['commit']: raise ValueError('Existing checkout differs from the manifest: ' + str(destination))
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    execute(['git', 'init', destination])
    execute(['git', '-C', destination, 'remote', 'add', 'origin', asset['url']])
    execute(['git', '-C', destination, 'fetch', '--depth', '1', 'origin', asset['commit']])
    execute(['git', '-C', destination, 'checkout', '--detach', 'FETCH_HEAD'])
    execute(['git', '-C', destination, 'submodule', 'update', '--init', '--recursive', '--depth', '1'])


def plan(root, manifest, models=False):
    return {'root': str(root), 'platform': manifest['platform'], 'python': manifest['python'],
        'repositories': [r for r in manifest['repositories'] if manifest.get('processingBackend','cuda') != 'cpu' or r['name'] != 'rife'], 'torch': manifest['torch'], 'torchIndex': manifest['torchIndex'],
        'archives': [manifest['ffmpeg'], manifest['sensor']],
        'models': manifest['models'] + ([manifest['rifeModel']] if manifest.get('processingBackend','cuda')=='cuda' else []) if models else [],
        'processingBackend':manifest.get('processingBackend','cuda'),
        'driverInstalledAutomatically': False, 'startsConversion': False,
        'note': 'Plan only unless --install is supplied. Review THIRD_PARTY_NOTICES.md before downloading.'}


def install(root, manifest, models, rife_archive=None):
    if os.name != 'nt' or sys.version_info[:2] != (3, 12):
        raise ValueError('Use Windows x64 CPython 3.12 for this tested engine profile.')
    if not shutil.which('git'): raise ValueError('Install Git for Windows first.')
    if (root / 'engine.json').exists():
        raise ValueError('This folder already has an engine. Use --check; choose a new root for a separate installation.')
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < 15 * 1024**3:
        raise ValueError('Allow at least 15 GiB of free space for engine installation, excluding movie workspaces.')
    backend=manifest.get('processingBackend','cuda')
    env = root / ('environments/desktop-v05-'+backend)
    python = env / 'Scripts/python.exe'
    if not python.exists(): execute([sys.executable, '-m', 'venv', env])
    execute([python, '-m', 'pip', 'install', 'torch==' + manifest['torch'],
             'torchvision==' + manifest['torchvision'], '--index-url', manifest['torchIndex']])
    execute([python, '-m', 'pip', 'install', '-r', REPO / 'requirements/engine-win-py312.txt'])
    for asset in manifest['repositories']:
        if backend=='cpu' and asset['name']=='rife':continue
        checkout(asset, root)
    downloads = root / 'downloads'
    ffmpeg_zip = verified_download(manifest['ffmpeg'], downloads / 'ffmpeg-9.0.2.zip')
    safe_extract(ffmpeg_zip, root / 'tools/ffmpeg')
    sensor_zip = verified_download(manifest['sensor'], downloads / 'LibreHardwareMonitor-0.9.6.zip')
    safe_extract(sensor_zip, root / 'tools/thermal-guard/LibreHardwareMonitor')
    cache = root / 'iw3-trial/cache'; cache.mkdir(parents=True, exist_ok=True)
    model_root = root / 'iw3-trial/rife-model'; model_root.mkdir(parents=True, exist_ok=True)
    if models:
        checkpoints = cache / 'iw3/pretrained_models/hub/checkpoints'
        for asset in manifest['models']: verified_download(asset, checkpoints / asset['name'])
    if models and backend=='cuda':
        archive = Path(rife_archive) if rife_archive else downloads / 'rife425.zip'
        if rife_archive and not archive.is_file():
            raise ValueError('The supplied RIFE archive does not exist.')
        if not archive.exists():
            execute([python, '-m', 'gdown', manifest['rifeModel']['url'], '-O', archive])
        if digest(archive) != manifest['rifeModel']['sha256']:
            raise ValueError('RIFE archive SHA-256 differs. Obtain 4.25 from the upstream README; do not use another model silently.')
        safe_extract(archive, model_root)
    ffmpeg = next((root / 'tools/ffmpeg').glob('*/bin/ffmpeg.exe'))
    weights = list(model_root.rglob('flownet.pkl'))
    train_log = weights[0].parent if weights else model_root / 'train_log'
    if weights and digest(weights[0]) != manifest['rifeModel']['weightSha256']:
        raise ValueError('Extracted RIFE weights failed verification.')
    config = {'python': str(python), 'iw3Repo': str(root / 'tools/nunif-iw3'), 'ffmpeg': str(ffmpeg),
        'ffprobe': str(ffmpeg.with_name('ffprobe.exe')), 'cache': str(cache),
        'rifeRepo': str(root / 'tools/Practical-RIFE'), 'rifeModel': str(train_log),
        'sensorLibrary': str(root / 'tools/thermal-guard/LibreHardwareMonitor'),
        'outputDir': str(root / 'Movies'), 'thermalMode': 'required', 'backend':backend}
    (root / 'engine.json').write_text(json.dumps(config, indent=2), encoding='utf8')
    print('Engine manifest created. Use Locate engine folder in the app.')
    print('CPU sensing still requires the signed PawnIO installer and explicit administrator approval in the app.')
    if not models: print('Model downloads were not requested. RIFE smoothing is unavailable until 4.25 is installed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=['cuda','cpu'],default='cuda',help='CPU profile works without an NVIDIA GPU; SDR/original FPS only')
    parser.add_argument('--root', type=Path, required=True, help='Separate engine directory, e.g. D:/CineVerse')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--install', action='store_true', help='Install the pinned engine; downloads several GB')
    group.add_argument('--check', action='store_true', help='Read the existing manifest and run selected-profile checks only')
    parser.add_argument('--download-models', action='store_true', help='Also fetch and verify the pinned model files')
    parser.add_argument('--rife-archive', type=Path, help='Official local 4.25 ZIP if Google Drive is unavailable')
    args = parser.parse_args(); root = args.root.expanduser().resolve()
    if args.rife_archive and not args.download_models:
        raise ValueError('--rife-archive requires --download-models.')
    manifest = json.loads(MANIFEST.read_text(encoding='utf8'))
    if args.profile=='cpu':manifest={**manifest,**manifest['cpuProfile']}
    else:manifest['processingBackend']='cuda'
    if root == REPO or root.is_relative_to(REPO): raise ValueError('Keep the engine outside the source repository.')
    if args.check:
        config = json.loads((root / 'engine.json').read_text(encoding='utf-8-sig'))
        execute([config['python'], '-u', REPO / 'worker/worker.py', 'check'],
                input=json.dumps({'config': config}), text=True, timeout=90)
    elif args.install: install(root, manifest, args.download_models, args.rife_archive)
    else: print(json.dumps(plan(root, manifest, args.download_models), indent=2))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, subprocess.SubprocessError, StopIteration) as error:
        print('Setup stopped: ' + str(error), file=sys.stderr); sys.exit(1)
