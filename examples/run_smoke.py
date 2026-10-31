"""Run a bounded local preview through the normal temperature supervisor.

Requires an installed engine and working PawnIO/CPU sensor; never starts a full
movie. Logs and reports stay in the selected output folder, outside Git.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'worker'))
from protection import start_cpu, cpu_reading


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True, help='Installed engine.json')
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backend', choices=('cpu','cuda','mps'), required=True)
    parser.add_argument('--resources',type=Path,default=ROOT,help='Packaged resource directory for QA')
    parser.add_argument('--seconds', type=int, choices=(3,10), default=3)
    args = parser.parse_args()
    out = args.output.resolve()
    if out == ROOT or out.is_relative_to(ROOT):
        raise ValueError('Keep private logs and rendered videos outside the source repository.')
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.engine.read_text(encoding='utf-8-sig'))
    config.update(backend=args.backend, outputDir=str(out), thermalMode='macos' if sys.platform=='darwin' else 'required')
    # Run this script using the selected engine Python, so setup and child agree.
    if Path(sys.executable).resolve() != Path(config['python']).resolve():
        raise ValueError('Run this helper with the Python executable from your engine manifest.')
    if sys.platform=='darwin':
        from macos_platform import status
        if not status(config)['ready']:raise ValueError('Apple thermal state is not ready; no conversion started.')
    else:
        config.update(start_cpu(config, os.getpid()))
        for attempt in range(80):
            try:cpu_reading(config);break
            except (OSError,ValueError):time.sleep(.25)
        else:raise ValueError('CPU sensor did not become ready. No conversion started.')
    request = dict(source=str(args.video.resolve()), outputDir=str(out), strength=1.5,
        stereoMethod='forward_inpaint',fpsMode='original',preview=True,
        previewStart=0,previewSeconds=args.seconds)
    began = time.monotonic()
    with (out/'smoke-errors.log').open('w',encoding='utf8') as errors:
        child = subprocess.Popen([config['python'],'-u',str(args.resources/'worker/worker.py'),'run'],
            start_new_session=os.name!='nt',env=dict(os.environ,**({'CINEVERSE_OWN_PROCESS_GROUP':'1'} if sys.platform=='darwin' else {})),
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True,
            encoding='utf8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            child.stdin.write(json.dumps(dict(config=config,request=request)));child.stdin.close()
            with (out/'smoke-events.jsonl').open('w',encoding='utf8') as log:
                for line in child.stdout:
                    log.write(line);log.flush();print(line.rstrip(),flush=True)
            result = child.wait()
        finally:
            # Kill supervisor AND descendants if this smoke harness is interrupted.
            if child.poll() is None:
                from protection import identity, stop_tree
                target = identity(child.pid)
                if target:stop_tree(target)
                else:child.kill()
                child.wait(timeout=10)
            child.stdout.close()
    (out/'smoke-result.json').write_text(json.dumps(dict(returncode=result,
        backend=args.backend,seconds=args.seconds,elapsedSeconds=time.monotonic()-began),indent=2))
    return result


if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('Preview stopped: '+str(error),file=sys.stderr);sys.exit(1)
