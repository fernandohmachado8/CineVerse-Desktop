"""CineVerse desktop worker. NDJSON progress on stdout; no shell execution."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from fractions import Fraction

FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
DEFAULT_STRENGTH = 1.5
DEFAULT_STEREO_METHOD = 'forward_inpaint'


def stereo_method(request):
    # Old checkpoints omitted a method and always used row_flow_v3.
    method = request.get('stereoMethod', 'row_flow_v3' if request.get('resumeJob') else DEFAULT_STEREO_METHOD)
    if method not in ('forward_inpaint', 'row_flow_v3'):
        raise ValueError('Choose neural or fast gap filling.')
    return method


def emit(kind, **data):
    print(json.dumps({'type': kind, **data}), flush=True)


def probe(config, path):
    path = Path(path)
    if not path.is_file():
        raise ValueError('Video file not found. Choose an existing local video.')
    p = subprocess.run([config['ffprobe'], '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                       capture_output=True, text=True, creationflags=FLAGS, timeout=45)
    if p.returncode:
        raise ValueError('Could not read this video. ' + p.stderr[-1500:])
    info = json.loads(p.stdout)
    video = next((s for s in info['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')), None)
    if not video:
        raise ValueError('This file does not contain a video stream.')
    rate = video.get('avg_frame_rate', '0/1')
    try: fps = float(Fraction(rate))
    except (ZeroDivisionError, ValueError): fps = 0
    return {'path': str(path.resolve()), 'width': video['width'], 'height': video['height'], 'fps': fps, 'rate': rate,
            'duration': float(info['format'].get('duration', video.get('duration', 0))),
            'videoStart': float(video.get('start_time', 0)), 'codec': video['codec_name'],
            'hdr': video.get('color_transfer') in ('smpte2084', 'arib-std-b67'),
            'transfer':video.get('color_transfer'), 'primaries':video.get('color_primaries'),
            'pixelFormat':video.get('pix_fmt',''), 'frames':int(video.get('nb_frames',0) or 0),
            'dolbyVision':any('dovi' in s.get('side_data_type','').lower() for s in video.get('side_data_list',[])),
            'sar': video.get('sample_aspect_ratio', '1:1'),
            'hasAudio': any(s['codec_type'] == 'audio' for s in info['streams']),
            'bytes': path.stat().st_size}


def check(config, gpu=True):
    for key in ('python', 'ffmpeg', 'ffprobe'):
        if not Path(config.get(key, '')).is_file():
            raise ValueError(f'{key} is missing. Set its executable path in Engine settings.')
    if not (Path(config.get('iw3Repo', '')) / 'iw3/__main__.py').is_file():
        raise ValueError('iw3 checkout not found. Select the nunif repository folder in Engine settings.')
    if not config.get('cache'):
        raise ValueError('Choose a folder for the model cache in Engine settings.')
    result = {'ready': True, 'neuralReady': (Path(config['iw3Repo']) / 'iw3/forward_inpaint.py').is_file(),
              'rifeReady': (Path(config.get('rifeModel', '')) / 'flownet.pkl').is_file()
              and (Path(config.get('rifeRepo', '')) / 'model/pytorch_msssim').is_dir()}
    if gpu:
        import torch
        from hardware import capabilities
        result.update(capabilities(config, torch), torch=torch.__version__)
    return result


def validate(request, media):
    stereo_method(request)
    strength = float(request.get('strength', 3 if request.get('resumeJob') else DEFAULT_STRENGTH))
    if not math.isfinite(strength) or not 0 <= strength <= 5:
        raise ValueError('Depth strength must be between 0 and 5.')
    if request.get('fpsMode') not in ('original', '60'):
        raise ValueError('Choose original frame rate or 60 FPS.')
    if media['hdr'] and (media.get('transfer')!='smpte2084' or media.get('primaries')!='bt2020'
                         or '10' not in media.get('pixelFormat','') and '12' not in media.get('pixelFormat','')):
        raise ValueError('HDR10 (10-bit BT.2020/PQ) is supported. HLG and unidentified HDR formats are not supported.')
    if media.get('dolbyVision'):raise ValueError('Dolby Vision preservation is not supported. Choose an HDR10 or SDR source.')
    if not math.isfinite(media['fps']) or not math.isfinite(media['duration']) or not 1 <= media['fps'] <= 60 or media['duration'] <= 0:
        raise ValueError('This build supports finite videos at 1–60 FPS.')
    if media['sar'] not in ('1:1', 'N/A', '0:1'):
        raise ValueError('Anamorphic pixels are not supported yet. Export a square-pixel SDR source first.')
    start = float(request.get('previewStart', 0)) if request.get('preview') else 0
    seconds = float(request.get('previewSeconds', 10)) if request.get('preview') else media['duration']
    if not math.isfinite(start) or not 0 <= start < media['duration']:
        raise ValueError('Preview start must be inside the video.')
    if not math.isfinite(seconds) or seconds <= 0 or (request.get('preview') and seconds > 180):
        raise ValueError('Preview duration must be greater than zero and no more than 180 seconds.')
    return strength, start, min(seconds, media['duration'] - start)


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def process(command, stage, log, env=None, cwd=None, duration=None):
    emit('progress', stage=stage, percent=None, eta=None, message='Starting…')
    began = time.monotonic(); last_emit = 0; last_percent = None
    with log.open('a', encoding='utf8') as output:
        output.write('\n' + json.dumps(command) + '\n')
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding='utf8', errors='replace', env=env, cwd=cwd, creationflags=FLAGS) as child:
            for line in child.stdout:
                output.write(line); output.flush()
                percent = None
                match = re.search(r'(\d+)%\|', line)
                if match: percent = float(match.group(1))
                if duration and line.startswith('out_time_us='):
                    try: percent = min(99, int(line.split('=')[1]) / 1e6 / duration * 100)
                    except ValueError: pass
                if line.startswith('{'):
                    try:
                        message = json.loads(line)
                        if 'frames' in message and 'total' in message:
                            percent = message['frames'] / max(message['total'], 1) * 100
                    except ValueError: pass
                now = time.monotonic()
                if percent is not None and now - last_emit > .2:
                    # iw3 has several internal progress bars. Reset the stage clock on a new pass.
                    if last_percent is not None and percent < last_percent - 10: began = now
                    eta = (now - began) * (100 - percent) / percent if percent > 1 else None
                    emit('progress', stage=stage, percent=round(percent, 1), eta=eta, message='Processing')
                    last_emit, last_percent = now, percent
            if child.wait():
                tail = log.read_text(encoding='utf8')[-2500:]
                hint = ' GPU memory was exhausted. Close other GPU applications and try a shorter preview.' if 'out of memory' in tail.lower() else ''
                raise RuntimeError(f'{stage} failed.{hint} See {log}\n{tail}')
    emit('progress', stage=stage, percent=100, eta=0, message='Stage complete')


def timeline(path, hardware=False):
    import av
    options={}
    if hardware:
        from av.codec.hwaccel import HWAccel
        options['hwaccel']=HWAccel(device_type='cuda',device='0',is_hw_owned=True,allow_software_fallback=False)
    with av.open(str(path),**options) as container:
        stream=container.streams.video[0]; stream.thread_type='AUTO'
        rate=Fraction(stream.average_rate); first=last=None; count=0; max_error=0
        for frame in container.decode(stream):
            t=frame.pts * frame.time_base
            if first is None: first=t
            max_error=max(max_error,abs(float(t-first-Fraction(count,1)/rate)))
            last=t; count+=1
            if count%3600==0:emit('progress',stage='Verifying video frames',percent=None,eta=None,message=f'{count:,} frames decoded')
        if not count: raise ValueError('Output contains no decoded frames.')
        return dict(frames=count,rate=str(rate),first=float(first),last=float(last),maxGridError=max_error,
                    width=stream.width,height=stream.height)


def audio_hash(ffmpeg, path):
    result = subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-map', '0:a:0', '-c:a', 'copy',
                             '-f', 'hash', '-hash', 'sha256', '-'], capture_output=True, text=True, creationflags=FLAGS)
    if result.returncode: raise RuntimeError('Audio verification failed: ' + result.stderr[-1000:])
    return result.stdout.strip()


if __name__=='__main__':
    payload=json.load(sys.stdin); config=payload['config']; request=payload.get('request',{})
    try:
        if sys.argv[1]=='check': print(json.dumps(check(config)))
        elif sys.argv[1]=='probe': print(json.dumps(probe(config,request['source'])))
        elif sys.argv[1]=='run':
            from protection import supervise
            supervise(config,request,emit)
        elif sys.argv[1]=='convert':
            # Internal child of the independent thermal supervisor, not a UI command.
            if config.get('resolvedBackend') == 'cpu' or config.get('backend') == 'cpu':
                from protection import limit_cpu_process
                # Windows venv launchers may spawn the real interpreter before
                # the supervisor applies affinity. Reapply inside that interpreter.
                limit_cpu_process()
            from pipeline import run
            run(config,request)
        elif sys.argv[1]=='thermal':
            from protection import status
            print(json.dumps(status(config)))
        elif sys.argv[1]=='sensor':
            from protection import start_cpu
            print(json.dumps(start_cpu(config,request['parentPid'])))
        elif sys.argv[1]=='discover':
            from engine_setup import discover
            print(json.dumps(discover(config,request['roots'])))
        elif sys.argv[1]=='plan':
            from pipeline import plan
            print(json.dumps(plan(config,request)))
        elif sys.argv[1]=='jobs':
            from pipeline import jobs
            print(json.dumps(jobs(config)))
        else: raise ValueError('Unknown worker command')
    except Exception as error:
        if sys.argv[1] in ('run','convert'): emit('error',message=str(error))
        else: print(str(error),file=sys.stderr)
        sys.exit(1)
