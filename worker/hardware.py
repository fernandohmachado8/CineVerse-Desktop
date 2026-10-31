"""Explicit processing profiles. CPU compatibility never implies GPU acceleration."""
import subprocess
import sys

IS_MAC = sys.platform == 'darwin'

FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def resolve(config, torch):
    requested = config.get('backend', 'auto')
    if requested not in ('auto', 'cuda', 'cpu', 'mps'):
        raise ValueError('Choose Automatic, NVIDIA CUDA, Apple MPS, or CPU compatibility.')
    if requested == 'cpu': return 'cpu'
    if requested == 'mps':
        mps = getattr(getattr(torch, 'backends', None), 'mps', None)
        if not IS_MAC or not mps or not mps.is_available():
            raise ValueError('Apple MPS is unavailable. Choose CPU compatibility on this Mac.')
        return 'mps'
    # MPS remains opt-in until physical-Mac inference has been validated.
    if IS_MAC:
        if requested == 'cuda': raise ValueError('NVIDIA CUDA is not supported by this Mac build.')
        return 'cpu'
    if torch.cuda.is_available(): return 'cuda'
    if requested == 'cuda':
        raise ValueError('NVIDIA CUDA was selected but is unavailable. Choose CPU compatibility or install a compatible engine/driver.')
    return 'cpu'


def encoder_probe(ffmpeg, backend):
    args = [ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=black:s=256x256:d=0.05']
    args += ['-vf', 'format=p010le', '-c:v', 'hevc_nvenc', '-profile:v', 'main10'] if backend == 'cuda' else [
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-threads', '2']
    return subprocess.run(args + ['-f', 'null', '-'], capture_output=True, text=True,
                          creationflags=FLAGS, timeout=45)


def capabilities(config, torch, probe=True):
    backend = resolve(config, torch); note = None
    if probe:
        result = encoder_probe(config['ffmpeg'], backend)
        if result.returncode and backend == 'cuda' and config.get('backend', 'auto') == 'auto':
            backend = 'cpu'
            note = 'CUDA was detected but NVENC Main10 could not start. CPU compatibility was selected before conversion.'
            result = encoder_probe(config['ffmpeg'], backend)
        if result.returncode:
            raise ValueError(('NVENC Main10' if backend == 'cuda' else 'Software H.264/libx264') +
                             ' encoder is unavailable. Check FFmpeg and the selected engine. ' + result.stderr[-1000:])
    result = {'backend': backend, 'supportsHDR': backend == 'cuda', 'supports60': backend == 'cuda',
              'maxWidth': 1920 if backend == 'cuda' else 1280, 'depthResolution': 518 if backend == 'cuda' else 392,
              'codec': 'NVENC' if backend == 'cuda' else 'Software H.264', 'note': note,
              'gpu': torch.cuda.get_device_name(0) if backend == 'cuda' else 'Apple MPS · experimental · software encoding' if backend == 'mps' else 'CPU compatibility · software encoding',
              'nvencReady': backend == 'cuda'}
    result['platform'] = 'macos' if IS_MAC else 'windows' if sys.platform == 'win32' else 'other'
    if backend == 'mps':
        result.update(maxWidth=1280, depthResolution=392,
                      note='Experimental MPS inference with per-operation CPU fallback; software H.264 encoding. Not a validated GPU performance claim.')
    if backend == 'cuda':
        result['gpuUuid'] = 'GPU-' + str(torch.cuda.get_device_properties(0).uuid).removeprefix('GPU-')
    return result


def planned_backend(config):
    value = config.get('resolvedBackend') or config.get('backend') or 'cuda'
    return value if value in ('cpu','mps') else 'cuda'


def validate_profile(backend, request, media):
    if backend in ('cpu','mps'):
        if media['hdr']:
            raise ValueError('CPU compatibility currently supports SDR input only. Select the NVIDIA profile for HDR10; no SDR conversion was performed.')
        if request.get('fpsMode') != 'original':
            raise ValueError('CPU compatibility currently keeps Original FPS. Select Original FPS or the NVIDIA profile for RIFE smoothing.')
