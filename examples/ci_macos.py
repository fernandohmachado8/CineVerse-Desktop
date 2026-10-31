"""Bounded macOS CI preview using the packaged worker and a provisioned engine."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def check_owned_process_group():
    """Stop only a disposable private process tree, never a shared shell group."""
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from thermal.thermal_guard import identity,stop_tree
    import psutil
    other=subprocess.Popen([sys.executable,'-c','import time;time.sleep(90)'],start_new_session=True)
    code='import subprocess,sys,time;p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(90)"]);print(p.pid,flush=True);time.sleep(90)'
    child=subprocess.Popen([sys.executable,'-u','-c',code],start_new_session=True,stdout=subprocess.PIPE,text=True)
    target=None
    try:
        grandchild=int(child.stdout.readline().strip());target=identity(child.pid)
        assert target and os.getpgid(child.pid)==child.pid
        try:stop_tree(dict(target,created=target['created']-1))
        except RuntimeError:pass
        else:raise AssertionError('A stale process identity was accepted')
        assert child.poll() is None and other.poll() is None
        stop_tree(target);child.wait(timeout=5)
        for _ in range(50):
            if not psutil.pid_exists(grandchild) or psutil.Process(grandchild).status()==psutil.STATUS_ZOMBIE:break
            time.sleep(.1)
        else:raise AssertionError('The disposable grandchild was not stopped')
        assert other.poll() is None
        return dict(ownedTreeStopped=True,unrelatedProcessPreserved=True,staleIdentityRefused=True)
    finally:
        if child.poll() is None:
            stop_tree(target or identity(child.pid))
        child.wait(timeout=5);child.stdout.close()
        other.terminate();other.wait(timeout=5)

root=Path(sys.argv[1]).resolve();resources=Path(sys.argv[2]).resolve()
process_protection=check_owned_process_group()
config=json.loads((root/'engine.json').read_text(encoding='utf8'))
source=root/'qa-synthetic.mp4';out=root/'qa-output'
subprocess.run([config['ffmpeg'],'-v','error','-n','-f','lavfi','-i','testsrc2=size=640x360:rate=1:duration=3',
    '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=3','-c:v','libx264','-threads','2',
    '-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],check=True)
subprocess.run([config['python'],str(Path(__file__).with_name('run_smoke.py')),'--engine',str(root/'engine.json'),
    '--video',str(source),'--output',str(out),'--backend','cpu','--seconds','3','--resources',str(resources)],check=True)
report=json.loads(next(p for p in out.glob('*.json') if p.name!='smoke-result.json').read_text(encoding='utf8'))
events=[json.loads(line) for line in (out/'smoke-events.jsonl').read_text(encoding='utf8').splitlines()]
states=[e['cpu']['thermalState'] for e in events if e['type']=='thermal' and 'thermalState' in e.get('cpu',{})]
assert states and report['backend']=='cpu' and report['outputTimeline']['frames']==3
assert report['outputTimeline']['maxGridError']==0 and report['sourceCheckPassed'] and report['preparedAudioPreserved']
summary=dict(platform='macOS arm64 hosted runner',backend='cpu',source='Generated test pattern; three seconds at 1 FPS',
    result=json.loads((out/'smoke-result.json').read_text(encoding='utf8')),timeline=report['outputTimeline'],
    sourceCheckPassed=report['sourceCheckPassed'],preparedAudioPreserved=report['preparedAudioPreserved'],quality=report['quality'],
    thermalStates=sorted(set(states)),thermalStateSamples=len(states),
    processProtection=process_protection,
    limitations=['Hosted runner, not headset playback or physical-Mac MPS performance testing.','Only a three-frame synthetic CPU conversion; no full movie.','Ad-hoc signed development app, not Developer ID notarized.'])
Path('macos-smoke-summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf8')
print(json.dumps(summary,indent=2))
