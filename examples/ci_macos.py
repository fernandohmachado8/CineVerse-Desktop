"""Bounded macOS CI preview using the packaged worker and a provisioned engine."""
import json
import os
from pathlib import Path
import subprocess
import sys

root=Path(sys.argv[1]).resolve();resources=Path(sys.argv[2]).resolve()
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
    limitations=['Hosted runner, not headset playback or physical-Mac MPS performance testing.','Only a three-frame synthetic CPU conversion; no full movie.','Ad-hoc signed development app, not Developer ID notarized.'])
Path('macos-smoke-summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf8')
print(json.dumps(summary,indent=2))
