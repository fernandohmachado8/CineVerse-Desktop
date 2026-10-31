"""macOS system thermal state, not Celsius. Uses only the built-in Foundation API."""
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

SCRIPT = 'ObjC.import("Foundation"); JSON.stringify({thermalState: Number($.NSProcessInfo.processInfo.thermalState)})'
LABELS = ('Nominal','Fair','Serious','Critical')


def thermal_status(config):
    result=subprocess.run(['/usr/bin/osascript','-l','JavaScript','-e',SCRIPT],capture_output=True,text=True,timeout=3,check=True)
    value=json.loads(result.stdout)['thermalState']
    if type(value) is not int or value not in range(4):raise ValueError('Invalid Apple system thermal state')
    return dict(mode='macos',ready=value<2,limits={'system':{'seriousSeconds':10,'critical':'immediate','sensorLossSeconds':30}},
        cpu=dict(state='ready' if value<2 else 'too_hot',thermalState=value,label=LABELS[value],
                 message='Apple reports elevated system thermal pressure.' if value>=2 else None),
        gpu=dict(state='not_separate',label='Shared system state'),gpuUuid=None)


def status(config):
    try:return thermal_status(config)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        return dict(mode='macos',ready=False,cpu=dict(state='unavailable',message='Apple thermal state unavailable: '+str(error)),
            gpu=dict(state='not_separate',label='Shared system state'),limits={})


class Monitor:
    def __init__(self, now):self.last_good=now;self.serious_since=None
    def sample(self, now, reading):
        value=reading.get('cpu',{}).get('thermalState')
        if type(value) is not int or value not in range(4):
            self.serious_since=None
            return 'Apple thermal-state sensor unavailable for 30 seconds.' if now-self.last_good>=30 else None
        self.last_good=now
        if value==3:return 'Apple system thermal state is Critical.'
        if value==2:
            if self.serious_since is None:self.serious_since=now
            if now-self.serious_since>=10:return 'Apple system thermal state stayed Serious for 10 seconds.'
        else:self.serious_since=None
        return None


def watch_parent():
    """The native host/worker creates this private process group before exec.

    If its parent disappears, terminate our own group, including subprocesses.
    Never signal the calling shell's group when run manually.
    """
    if os.environ.get('CINEVERSE_OWN_PROCESS_GROUP')!='1':return
    if os.getpgrp()!=os.getpid():raise RuntimeError('Refusing to monitor an unowned process group')
    parent=os.getppid()
    def watch():
        while True:
            time.sleep(1)
            if os.getppid()!=parent:
                os.killpg(os.getpgrp(),signal.SIGKILL)
    threading.Thread(target=watch,daemon=True).start()
