"""Bounded local engine discovery; no downloads and no recursive disk searches."""
import json
from pathlib import Path
import shutil
import sys
IS_MAC = sys.platform=='darwin'

LABELS = {'python': 'AI Python', 'iw3Repo': 'iw3', 'ffmpeg': 'FFmpeg', 'ffprobe': 'FFprobe',
          'cache': 'Model cache', 'rifeRepo': 'RIFE code', 'rifeModel': 'RIFE weights',
          'sensorLibrary': 'CPU sensor library'}


def exists(key, value):
    if not value: return False
    p = Path(value)
    if key in ('python', 'ffmpeg', 'ffprobe'): return p.is_file()
    if key == 'iw3Repo': return (p / 'iw3/__main__.py').is_file()
    if key == 'rifeRepo': return (p / 'model/pytorch_msssim').is_dir()
    if key == 'rifeModel': return (p / 'flownet.pkl').is_file()
    if key == 'sensorLibrary': return (p / 'LibreHardwareMonitorLib.dll').is_file()
    return p.is_dir()


def discover(current, roots):
    result = dict(current)
    def accept(key, value):
        if not exists(key, result.get(key)) and exists(key, value): result[key] = str(value)
    for root in map(Path, roots):
        # Explicit root or a known CineVerse installation folder, at most one level.
        for manifest in (root / 'engine.json', root / 'portable.json', root / 'App/portable.json'):
            try:
                saved = json.loads(manifest.read_text(encoding='utf-8-sig'))
                for key in LABELS: accept(key, saved.get(key))
                if not result.get('backend') and saved.get('backend') in ('auto','cpu','cuda','mps','rocm'): result['backend'] = saved['backend']
                if result.get('python')==saved.get('python'):
                    for key in ('managedBackend','runtimeProbePassed','setupTorchVersion','setupGpuName','setupRecipeVersion'):
                        if key in saved:result[key]=saved[key]
                if not result.get('outputDir') and saved.get('outputDir'): result['outputDir'] = saved['outputDir']
            except (OSError, ValueError, TypeError): pass
        patterns = {'python': ['environments/*/Scripts/python.exe', 'runtime/python*/python.exe'],
                    'iw3Repo': ['tools/nunif-iw3'], 'ffmpeg': ['tools/ffmpeg*/bin/ffmpeg.exe'],
                    'ffprobe': ['tools/ffmpeg*/bin/ffprobe.exe'], 'cache': ['iw3-trial/cache'],
                    'rifeRepo': ['tools/Practical-RIFE'], 'rifeModel': ['iw3-trial/rife-model/train_log'],
                    'sensorLibrary': ['tools/thermal-guard/LibreHardwareMonitor']}
        if IS_MAC:
            patterns.update(python=['environments/*/bin/python3'],ffmpeg=['tools/ffmpeg/ffmpeg'],ffprobe=['tools/ffmpeg/ffprobe'])
        for key, globs in patterns.items():
            for pattern in globs:
                for path in sorted(root.glob(pattern), reverse=True): accept(key, path)
        if not result.get('outputDir') and root.is_dir(): result['outputDir'] = str(root / 'Movies')
    for key in ('ffmpeg', 'ffprobe'): accept(key, shutil.which(key))
    if IS_MAC:result['thermalMode']='macos'
    else:result.setdefault('thermalMode', 'required')
    return {'settings': result, 'components': [dict(key=k, label=label, found=exists(k, result.get(k)), optional=k in ('rifeRepo','rifeModel'))
            for k, label in LABELS.items() if not IS_MAC or k not in ('rifeRepo','rifeModel','sensorLibrary')]}
