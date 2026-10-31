"""Desktop 0.3: checkpointed HDR/SDR pipeline with neural gap filling."""
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from worker import emit,probe,check,validate,process,timeline,audio_hash,FLAGS,stereo_method

VERSION='0.3-neural-default-v1'
LEGACY_VERSION='0.2-hdr60-edge-v1'
GIB=1024**3


def atomic_json(path,data):
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w',encoding='utf8') as f:
        f.write(json.dumps(data,indent=2));f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def hash_file(path,stage='Checking file integrity'):
    size=path.stat().st_size;done=0;began=last=time.monotonic();h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(32*1024**2):
            h.update(block);done+=len(block);now=time.monotonic()
            if now-last>1:
                emit('progress',stage=stage,percent=100*done/max(1,size),
                     eta=(now-began)*(size-done)/done,message=f'{done/GIB:.1f} / {size/GIB:.1f} GB')
                last=now
    return h.hexdigest()


def identity(path,full):
    s=path.stat()
    if full:value=hash_file(path,'Checking original movie')
    else:
        h=hashlib.sha256()
        with path.open('rb') as f:
            for offset in sorted({0,max(0,s.st_size//2-1024**2),max(0,s.st_size-2*1024**2)}):
                f.seek(offset);h.update(f.read(2*1024**2))
        value=h.hexdigest()
    return {'bytes':s.st_size,'mtimeNS':s.st_mtime_ns,'hash':value,
            'method':'full SHA-256' if full else 'sampled SHA-256 (start/middle/end), size and mtime'}


def plan(config,request):
    media=probe(config,request.get('source',''))
    strength,start,seconds=validate(request,media)
    smooth=request.get('fpsMode')=='60' and media['fps']<60
    budget=max(GIB,int(seconds*(24 if smooth else 16)*1024**2))
    directory=Path(request.get('outputDir') or config.get('outputDir') or '.')
    parent=directory
    while not parent.exists() and parent!=parent.parent:parent=parent.parent
    free=shutil.disk_usage(parent).free
    # Conservative range informed by the tested RTX 4090 passage, not a completion promise.
    method=stereo_method(request)
    factor=((4.2,7.0) if smooth else (1.3,2.7)) if method=='forward_inpaint' else ((2.7,4.0) if smooth else (.6,1.3))
    return {'media':media,'strength':strength,'start':start,'seconds':seconds,'hdr':media['hdr'],
        'smooth':smooth,'stereoMethod':method,'targetFPS':60 if request.get('fpsMode')=='60' else media['fps'],
        'spaceBudgetBytes':budget,'freeBytes':free,'enoughSpace':free>=budget,
        'estimatedSecondsLow':seconds*factor[0],'estimatedSecondsHigh':seconds*factor[1],
        'outputEstimateBytesLow':int(seconds*1.5e6),'outputEstimateBytesHigh':int(seconds*4e6),
        'note':'Time and file size vary with scene motion. Space budget includes temporary videos. HDR is retained from HDR10 sources.'}


def alive(pid):
    if os.name=='nt':
        import ctypes
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.OpenProcess.restype=ctypes.c_void_p;k.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]
        handle=k.OpenProcess(0x1000,False,int(pid))
        if not handle:return ctypes.get_last_error()==5
        code=ctypes.c_uint32();k.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
        k.CloseHandle.argtypes=[ctypes.c_void_p]
        ok=k.GetExitCodeProcess(handle,ctypes.byref(code));k.CloseHandle(handle)
        return bool(ok and code.value==259)
    try:os.kill(int(pid),0);return True
    except (OSError,ValueError):return False


def jobs(config):
    root=Path(config.get('outputDir') or '.')/'.cineverse-jobs';result=[]
    if root.is_dir():
        for p in root.glob('*/job.json'):
            try:
                s=json.loads(p.read_text());lock=p.parent/'active.json'
                running=lock.exists() and alive(json.loads(lock.read_text())['pid'])
                if s.get('pipeline') in (VERSION,LEGACY_VERSION) and s.get('status')!='complete':
                    saved_request=canonical_request(s['request'],s['pipeline'])
                    result.append({'path':str(p),'source':s['request']['source'],'request':saved_request,
                        'completedStages':list(s.get('completed',{})),'running':running,'updated':p.stat().st_mtime,
                        'error':s.get('error'),'status':s.get('status'),'log':str(p.parent/'conversion.log')})
            except (OSError,ValueError,KeyError):continue
    return sorted(result,key=lambda x:x['updated'],reverse=True)[:10]


def resume_path(directory,value):
    path=Path(value).resolve();root=(directory/'.cineverse-jobs').resolve()
    if path.name!='job.json' or path.parent.parent!=root:
        raise ValueError('Resume job must belong to this output folder.')
    return path


def canonical_request(request,version=VERSION):
    result={k:v for k,v in request.items() if k!='resumeJob'}
    result.setdefault('stereoMethod','row_flow_v3' if version==LEGACY_VERSION else 'forward_inpaint')
    result.setdefault('strength',3 if version==LEGACY_VERSION else 1.5)
    return result


def run(config,request):
    capabilities=check(config)
    p=plan(config,request);media=p['media'];hdr=p['hdr'];smooth=p['smooth']
    method=p['stereoMethod']
    if method=='forward_inpaint' and not capabilities.get('neuralReady'):
        raise ValueError('This iw3 checkout lacks neural gap filling. Update the official checkout or select Fast gap filling.')
    if smooth and not capabilities['rifeReady']:raise ValueError('60 FPS requires the configured official RIFE 4.25 model.')
    if not request.get('outputDir'):raise ValueError('Choose an output folder.')
    directory=Path(request['outputDir']).resolve();directory.mkdir(parents=True,exist_ok=True)
    source=Path(media['path']);source_stat=source.stat()
    clean_request=canonical_request({**request,'stereoMethod':method,'strength':p['strength']})
    if request.get('resumeJob'):
        state_path=resume_path(directory,request['resumeJob']);state=json.loads(state_path.read_text());work=state_path.parent
        if state.get('pipeline') not in (VERSION,LEGACY_VERSION) or canonical_request(state['request'],state['pipeline'])!=clean_request:
            raise ValueError('Saved settings differ. Resume with the saved depth and gap-filling method, or start a new preview.')
        if state.get('status')=='complete':raise ValueError('This job is already complete.')
    else:
        if not p['enoughSpace']:raise ValueError(f"Allow {p['spaceBudgetBytes']/GIB:.0f} GB of free temporary space on the output drive.")
        work=directory/'.cineverse-jobs'/uuid.uuid4().hex[:10];work.mkdir(parents=True)
        state_path=work/'job.json';state={'pipeline':VERSION,'request':clean_request,'completed':{},'status':'starting'}
    lock=work/'active.json'
    if lock.exists():
        old=json.loads(lock.read_text())
        if alive(old['pid']):raise ValueError('This saved job is still running.')
        lock.unlink()
    with lock.open('x') as f:json.dump({'pid':os.getpid()},f)
    log=work/'conversion.log'
    emit('started',workDir=str(work),log=str(log),message='Checking source and saved stages')
    def save():atomic_json(state_path,state)
    save()
    try:
        current=identity(source,not request.get('preview'))
        if state.get('sourceIdentity') and state['sourceIdentity']!=current:raise ValueError('The source movie changed. Start a new job.')
        state['sourceIdentity']=current;state['status']='running';state.pop('error',None);save()
        completed=state['completed'];reused=[];invalidated=False
        def stage(name,outputs,partials,action):
            nonlocal invalidated
            state['currentStage']=name;save()
            emit('progress',stage=name,percent=None,eta=None,message='Checking saved stage' if name in completed else 'Starting')
            cached=completed.get(name)
            if cached and not invalidated:
                good=True
                for rel,expected in cached['hashes'].items():
                    path=work/rel
                    if path.resolve().parent!=work.resolve() or not path.is_file() or hash_file(path,f'Checking saved {name}')!=expected:good=False;break
                if good:reused.append(name);emit('progress',stage=name,percent=100,eta=0,message='Reused completed stage');return
            if cached:invalidated=True
            completed.pop(name,None)
            # Delete only known generated partial files inside this private job folder.
            for rel in set(outputs+partials):
                path=work/rel
                if path.resolve().parent!=work.resolve():raise ValueError('Unsafe intermediate path')
                if path.is_file():path.unlink()
            used=sum(x.stat().st_size for x in work.iterdir() if x.is_file())
            remaining=max(GIB,p['spaceBudgetBytes']-used)
            if shutil.disk_usage(directory).free<remaining:raise ValueError('Not enough temporary space. Free space or select another drive, then resume.')
            began=time.monotonic();action()
            hashes={rel:hash_file(work/rel,f'Checking {name} output') for rel in outputs}
            completed[name]={'hashes':hashes,'seconds':time.monotonic()-began};save()
        ffmpeg=config['ffmpeg'];here=Path(__file__).parent
        prepared=work/'prepared.mp4';reference=work/'smooth60.mp4' if smooth else prepared
        vf=f"scale=w='trunc(min(1920,iw)/2)*2':h=-2,setsar=1,fps={media['rate']}"
        codec='hevc_nvenc' if hdr else 'h264_nvenc';fmt='p010le' if hdr else 'yuv420p'
        prepare=[ffmpeg,'-hide_banner','-nostdin','-n','-ss',str(p['start']),'-hwaccel','cuda','-i',str(source),'-t',str(p['seconds']),
            '-map','0:v:0','-map','0:a:0?','-vf',vf,'-c:v',codec,'-preset','p6','-rc','constqp','-qp','16','-pix_fmt',fmt,
            *(['-profile:v','main10','-tag:v','hvc1'] if hdr else []),'-c:a','aac','-b:a','256k','-ac','2',
            '-movflags','+faststart','-progress','pipe:1','-nostats',str(prepared)]
        stage('Preparing video',['prepared.mp4'],[],lambda:process(prepare,'Preparing HDR10 video' if hdr else 'Preparing SDR video',log,duration=p['seconds']))
        prepared_meta=probe(config,prepared)
        if hdr:
            from hdr_trial import hdr_params
            if hdr_params(prepared,config['ffprobe'])!=hdr_params(source,config['ffprobe']):raise ValueError('Preparation did not retain HDR10 metadata.')
        env=dict(os.environ,NUNIF_HOME=config['cache'],HF_HOME=str(Path(config['cache'])/'huggingface'),TORCH_HOME=str(Path(config['cache'])/'torch'),PYTHONNOUSERSITE='1',PYTHONUNBUFFERED='1')
        base=[config['python'],'-u','-m','iw3','--depth-model','Any_V2_S','--gpu','0','--method',method,
            '--synthetic-view','right','--divergence',str(p['strength']),'--convergence','.5','--resolution','518',
            '--edge-dilation','2','--ema-normalize','--scene-detect','--scene-cache-dir',str(work/'cuts'),
            '--video-codec',codec,'--pix-fmt','yuv420p10le' if hdr else 'yuv420p','--colorspace','auto','--crf','12','--preset','p6','--batch-size','2']
        if method=='forward_inpaint':base+=['--inpaint-model','light_inpaint_v1']
        if smooth:
            def detect():
                process(base+['--input',str(prepared),'--output',str(work/'unused.mp4'),'--scene-detect-only','--max-fps',str(media['fps'])],
                    'Detecting scene cuts',log,env,config['iw3Repo'])
                cuts=list((work/'cuts').glob('*.json'))
                if len(cuts)!=1:raise RuntimeError('Scene detection did not produce a unique cache')
                shutil.copyfile(cuts[0],work/'source-cuts.json')
            stage('Detecting scene cuts',['source-cuts.json'],[],detect)
            interp=here/('interpolate_hdr_rife.py' if hdr else 'interpolate_rife.py')
            command=[config['python'],'-u',str(interp),'--source',str(prepared),'--output',str(reference),
                '--model',config['rifeModel'],'--rife-repo',config['rifeRepo'],'--cuts',str(work/'source-cuts.json'),'--ffmpeg',ffmpeg]
            if hdr:command+=['--iw3',config['iw3Repo'],'--ffprobe',config['ffprobe']]
            extra=['smooth60_raw.mp4','smooth60_hdr.mp4','smooth60_video.mp4']
            outputs=['smooth60.mp4','smooth60.json']+(['smooth60.frames.json'] if hdr else [])
            stage('Generating 60 FPS',outputs,extra,lambda:process(command,'Generating HDR 60 FPS' if hdr else 'Generating 60 FPS',log,env))
            for rel in extra:
                path=work/rel
                if path.is_file():path.unlink()
        ref_meta=probe(config,reference)
        decay=.75**(media['fps']/60) if smooth else .75
        raw=work/'stereo.mp4'
        export=[config['python'],'-u',str(here/'iw3_export.py'),*base[4:],'--input',str(reference),'--output',str(raw),
                '--max-fps',str(ref_meta['fps']),'--ema-decay',str(decay)]
        stage('Creating stereo depth',['stereo.mp4'],['_tmp_stereo.mp4','_error_stereo.mp4'],
            lambda:process(export,'Creating stereo depth · '+('neural gap filling' if method=='forward_inpaint' else 'fast gap filling'),log,env,config['iw3Repo']))
        tagged=work/'stereo_hdr.mp4' if hdr else raw
        final=work/'verified.mp4'
        def finalize():
            if hdr:
                from hdr_sei import add_static_hdr
                add_static_hdr(raw,reference,tagged)
            shift=ref_meta['videoStart']-probe(config,raw)['videoStart']
            process([ffmpeg,'-v','error','-nostdin','-n','-itsoffset',str(shift),'-i',str(tagged),'-i',str(reference),
                '-map','0:v:0','-map','1:a:0?','-c','copy','-copyts','-avoid_negative_ts','disabled',
                *(['-tag:v','hvc1'] if hdr else []),'-movflags','+faststart',str(final)],'Restoring audio and HDR metadata',log)
        stage('Finalizing video',['verified.mp4'],['stereo_hdr.mp4'],finalize)
        def verify():
            emit('progress',stage='Verifying output',percent=None,eta=None,message='Fully decoding reference and output with NVIDIA hardware')
            a=timeline(reference,hardware=True);b=timeline(final,hardware=True)
            height=((a['height']+16+63)//64)*64
            if b['frames']!=a['frames'] or b['width']!=2*a['width'] or b['height']!=height:raise RuntimeError('Stereo frame count/geometry verification failed')
            if abs(a['first']-b['first'])>.001 or abs(a['last']-b['last'])>.001 or b['maxGridError']>.001:raise RuntimeError('Video timing verification failed')
            if smooth and b['rate']!='60':raise RuntimeError('Expected 60 FPS')
            output_meta=probe(config,final)
            if hdr and hdr_params(reference,config['ffprobe'])!=hdr_params(final,config['ffprobe']):raise RuntimeError('HDR metadata verification failed')
            if ref_meta['hasAudio'] and audio_hash(ffmpeg,reference)!=audio_hash(ffmpeg,final):raise RuntimeError('Prepared audio changed')
            # Check crop-free coded geometry using FFprobe, plus sampled margins/content below.
            info=json.loads(subprocess.check_output([config['ffprobe'],'-v','error','-select_streams','v:0','-show_streams','-of','json',str(final)],creationflags=FLAGS))['streams'][0]
            if info['coded_height']!=height or info['height']!=height:raise RuntimeError('Hidden bottom crop was not eliminated')
            quality=verify_edges(reference,final,height,hdr)
            if source.stat().st_size!=source_stat.st_size or identity(source,not request.get('preview'))!=current:raise RuntimeError('Source integrity check changed')
            atomic_json(work/'verification.json',{'reference':a,'outputTimeline':b,'preparedAudioPreserved':True,'quality':quality,
                'HDR':hdr,'sourceIntegrity':current,'sourceCheckPassed':True,'stereoMetadata':output_meta})
        stage('Verifying output',['verification.json'],[],verify)
        verified=json.loads((work/'verification.json').read_text())
        safe=''.join(c if c.isalnum() or c in ' .-_' else '_' for c in source.stem)[:65]
        mode='preview' if request.get('preview') else 'full'
        name=f"{safe}_CineVerse_{mode}_d{p['strength']:g}_{'neural' if method=='forward_inpaint' else 'fast'}_{'60fps' if request['fpsMode']=='60' else 'original-fps'}_{'HDR10' if hdr else 'SDR'}_{work.name}_LRF_Full_SBS.mp4"
        destination=directory/name
        report={**verified,'source':str(source),'output':str(destination),'outputSha256':hash_file(final,'Checking final export'),
            'request':clean_request,'gpu':capabilities['gpu'],'pipeline':state['pipeline'],'checkpointedStages':completed,'reusedStages':reused,
            'log':str(log),'limitations':['First audio track is AAC stereo; subtitles/additional tracks omitted.',
                '60 FPS motion is AI-generated with cut guards; artifacts remain possible.',
                'Explicit black compatibility margins retain all image pixels.','Interrupted stages restart; completed verified stages can be resumed.']}
        if method=='forward_inpaint':report['limitations'].append('Neural gap filling invents disoccluded texture and may soften or flicker. It is not recovered footage.')
        if destination.exists():
            if hash_file(destination)!=report['outputSha256']:raise FileExistsError('A different export exists at the destination')
        else:os.link(final,destination)
        atomic_json(destination.with_suffix('.json'),report)
        state['status']='complete';state['output']=str(destination);save()
        # Publication succeeded: remove only known large intermediates in this job directory.
        for rel in ('prepared.mp4','smooth60.mp4','stereo.mp4','stereo_hdr.mp4','verified.mp4'):
            path=work/rel
            if path.is_file():path.unlink()
        emit('complete',output=str(destination),report=str(destination.with_suffix('.json')),log=str(log),
            frames=verified['outputTimeline']['frames'],fps=float(Fraction(verified['outputTimeline']['rate'])),message='Verified SBS export is ready')
    except Exception as exc:
        state['status']='interrupted';state['error']=str(exc);save();raise
    finally:
        if lock.exists():lock.unlink()


def black_level(hdr,full_range):
    return 0 if full_range else 64 if hdr else 16


def verify_edges(reference,output,encoded_height,hdr):
    import av
    import numpy as np
    sample_times=(0,.25,1,5,30,60,120)
    results=[];neutral=512 if hdr else 128;div=1023 if hdr else 255
    with av.open(str(reference)) as src,av.open(str(output)) as dst:
        h=src.streams.video[0].height;w=src.streams.video[0].width;top=((encoded_height-h)//4)*2
        def at(c,t):
            s=c.streams.video[0];c.seek(int(t/s.time_base),stream=s,backward=True)
            last=None
            for f in c.decode(s):
                last=f
                if float(f.pts*f.time_base)>=t:return f
            return last
        for target in sample_times:
            if target>=float(src.duration/av.time_base):continue
            a=at(src,target);b=at(dst,float(a.pts*a.time_base))
            if a is None or b is None:raise RuntimeError('Could not decode quality sample')
            black=black_level(hdr,b.color_range==2)
            dtype=np.uint16 if hdr else np.uint8
            arrays=[]
            for f in (a,b):arrays.append([np.frombuffer(p,dtype=dtype).reshape(p.height,-1)[:,:p.width] for p in f.planes])
            y=arrays[0][0].astype(float);z=arrays[1][0][top:top+h,:w].astype(float)
            mae=float(np.abs(y-z).mean());bottom=float(np.abs(y[-16:]-z[-16:]).mean())
            if mae/div>.02 or bottom/div>.03:raise RuntimeError('Source-eye image detail verification failed')
            guard=[]
            for i,p in enumerate(arrays[1]):
                rows=4 if i else 8;value=neutral if i else black
                mean=float(np.abs(np.concatenate((p[:rows],p[-rows:])).astype(float)-value).mean())
                if mean/div>.01:raise RuntimeError('Black compatibility margin verification failed')
                guard.append(mean)
            results.append({'time':target,'leftEyeMAE':mae,'bottomRowsMAE':bottom,'guardMeansYUV':guard})
    return {'samples':results,'topBlackRows':top,'bottomBlackRows':encoded_height-h-top,'moviePixelsRemoved':0}
