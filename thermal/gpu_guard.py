"""Independent NVIDIA GPU guard; leaves the running CPU guard uninterrupted."""
import argparse
import csv
import io
import json
import math
from pathlib import Path
import os
import subprocess
import time
from thermal_guard import Policy, identity, stop_tree, sensor_lost, atomic, alert


def parse_gpu(text, uuid):
    rows=list(csv.reader(io.StringIO(text.strip())))
    if len(rows)!=1 or len(rows[0])!=2 or rows[0][0].strip()!=uuid:
        raise ValueError('NVIDIA did not return the bound GPU UUID')
    value=float(rows[0][1].strip())
    if not math.isfinite(value) or not 1<value<130:
        raise ValueError('Invalid NVIDIA GPU core temperature')
    return value


def read_gpu(cfg):
    result=subprocess.run([cfg['nvidiaSmi'],'-i',cfg['gpuUuid'],
        '--query-gpu=uuid,temperature.gpu','--format=csv,noheader,nounits'],
        capture_output=True,text=True,timeout=2,check=True,creationflags=0x08000000)
    return parse_gpu(result.stdout,cfg['gpuUuid'])


def run(config_path):
    cfg=json.loads(config_path.read_text(encoding='utf-8-sig'))
    target=cfg['target'];root=config_path.parent
    status=root/'gpu-status.json'
    if identity(target['pid'])!=target:
        raise RuntimeError('Configured conversion is no longer running')
    policy=Policy('GPU',85,90)
    armed=False
    last_good=initial=time.monotonic()

    def record(state,**details):
        data=dict(state=state,timestamp=time.time(),guardPid=os.getpid(),target=target,
            gpuUuid=cfg['gpuUuid'],sensor='NVIDIA GPU core (not VRAM/hotspot)',
            thresholds={'sustainedC':85,'seconds':10,'immediateC':90},**details)
        atomic(status,data)
        return data

    record('waiting_for_sensor')
    while identity(target['pid'])==target:
        reason=None;temperature=None
        try:
            temperature=read_gpu(cfg)
            now=time.monotonic()
            reason=policy.sample(temperature,now)
            last_good=now
            if not armed:
                armed=True
                alert('CineVerse GPU protection is ACTIVE for the RTX 4090. Stop: 85 C for 10 seconds, or 90 C on a reading. Missing GPU readings for 30 seconds also stop this conversion. CPU protection remains separate.')
            record('active',gpuC=temperature,hotSeconds=0 if policy.hot_since is None else now-policy.hot_since)
        except (OSError,ValueError,KeyError,subprocess.SubprocessError) as exc:
            now=time.monotonic();policy.hot_since=None
            if sensor_lost(armed,now,last_good):
                reason='GPU sensor unavailable for 30 seconds after protection was armed'
            else:
                record('sensor_unavailable' if armed else 'waiting_for_sensor',message=str(exc),protectionPreviouslyArmed=armed)
            if not armed and now-initial>=300:
                record('not_armed',message='No valid GPU sensor received; GPU protection is NOT active')
                alert('CineVerse GPU protection could NOT start: no valid NVIDIA reading. CPU guard was not changed.')
                return
        if reason:
            record('stopping',reason=reason,gpuC=temperature)
            result=stop_tree(target)
            event=record('stopped',reason=reason,gpuC=temperature,termination=result)
            with (root/'gpu-events.jsonl').open('a',encoding='utf8') as f:
                f.write(json.dumps(event)+'\n')
            alert('CineVerse conversion STOPPED: '+reason+'. Source movie untouched. Completed stages can be manually resumed; current stage restarts.')
            return
        time.sleep(2)
    record('finished_monitoring',message='Bound conversion process ended; other jobs will not be monitored')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('config',type=Path)
    args=parser.parse_args()
    try:
        run(args.config)
    except Exception as exc:
        atomic(args.config.parent/'gpu-status.json',{'state':'guard_error','message':str(exc),'timestamp':time.time()})
        alert('CineVerse GPU guard ERROR; GPU protection cannot be guaranteed: '+str(exc))
        raise
