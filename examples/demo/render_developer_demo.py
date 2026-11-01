"""Create a developer walkthrough from real captures and recorded conversion evidence.

Diagrams explain implementation; they are not fabricated application screens.
The sample is an existing actual AI export. This renderer never runs inference.
Requires Python, NumPy, Pillow, FFmpeg and Windows Segoe UI/Consolas fonts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

WIDTH,HEIGHT,FPS,DURATION=1920,1080,30,178
INK=(233,241,237);MUTED=(171,190,185);GREEN=(174,218,188)
LINE=(55,83,77);PANEL=(20,36,38);AMBER=(226,186,121)
STEM='CineVerse-Developer-Demo-0.8.1'
CHAPTERS=[
    (0,7,'A local stereo-video pipeline'),
    (7,20,'Architecture and IPC'),
    (20,33,'Provisioning and hardware checks'),
    (33,45,'A bounded conversion request'),
    (45,62,'Depth, reprojection and neural filling'),
    (62,74,'Temporal controls'),
    (74,91,'Independent thermal supervision'),
    (91,104,'Stage recovery and integrity'),
    (104,114,'Original 2D sample'),
    (114,126,'Actual AI-converted SBS'),
    (126,143,'Measured export verification'),
    (143,156,'Optional paths and hardware scope'),
    (156,169,'Boundaries, tradeoffs and credits'),
    (169,178,'Inspect and reproduce'),
]
CAPTIONS=[
    'CineVerse Desktop coordinates a local stereo-video pipeline. This is an edited developer walkthrough of Windows 0.8.1.',
    'React invokes Tauri commands. Rust starts a Python supervisor and forwards newline-delimited JSON events to the interface.',
    'Automatic setup provisions private dependencies and checks the runtime and encoder. Hardware discovery alone does not certify inference performance.',
    'This is the actual normalized preview request, with paths omitted: ten seconds, depth 1.5, neural filling, Original FPS, CUDA.',
    'iw3 uses Depth Anything V2 Small for relative depth, forward reprojection for disparity, and light_inpaint_v1 for disoccluded texture.',
    'EMA depth normalization and scene-cut handling aim to reduce instability. This continuous sample does not test scene cuts or difficult movie motion.',
    'The independent supervisor owns the converter tree. Required temperature readings are checked before and during work. Software monitoring cannot guarantee safety.',
    'Stage hashes and source, settings and backend identity control recovery. A completed stage can be reused; an interrupted stage restarts.',
    'The original analytical animation is ten seconds at 24 FPS, 960 by 540, SDR, without audio. It is not an AI reconstruction.',
    'This is the previously recorded actual AI SBS export. The left view retains source imagery; the right view and hidden texture are synthesized.',
    'The recorded export has 240 frames at 24 FPS, zero timestamp-grid error, verified margins and no removed source pixels. Sampled encoding errors are not a quality rating.',
    'HDR10 and RIFE smoothing are separate supported NVIDIA paths, not used here. CPU, experimental Radeon and the separate Mac preview have narrower limits.',
    'This produces stereo screen depth, not a walkable 360-degree scene. CineVerse integrates existing models; credit belongs to iw3, Depth Anything V2 and optional Practical-RIFE.',
    'Inspect the immutable 0.8.1 application source and sanitized evidence. Reproduce a short preview before judging quality or attempting a long conversion.',
]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures',type=Path,required=True)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--sbs',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--ffmpeg',default='ffmpeg')
    parser.add_argument('--font-dir',type=Path,default=Path('C:/Windows/Fonts'))
    args=parser.parse_args()
    evidence=json.loads(args.evidence.read_text(encoding='utf8'))
    request=evidence['normalizedRequest'];conversion=evidence['conversion'];validation=evidence['validation']
    assert request['preview'] and request['previewSeconds']==10 and request['strength']==1.5
    assert request['stereoMethod']=='forward_inpaint' and request['fpsMode']=='original'
    assert evidence['application']['version']=='0.8.1' and validation['output']['frames']==240
    for file,key in ((args.source,'CineVerse-Sample-2D.mp4'),(args.sbs,'CineVerse-Sample-SBS-Depth-1.5.mp4')):
        assert hashlib.sha256(file.read_bytes()).hexdigest()==evidence['media'][key]['sha256'],'Sample bytes differ from recorded evidence'
    args.output_dir.mkdir(parents=True,exist_ok=True)
    output=args.output_dir/(STEM+'.mp4')
    if output.exists():raise FileExistsError('Preserving existing video: '+str(output))
    cache={};layout=[]
    def font(size,bold=False,mono=False):
        key=(size,bold,mono)
        if key not in cache:
            name='consola.ttf' if mono else 'segoeuib.ttf' if bold else 'segoeui.ttf'
            cache[key]=ImageFont.truetype(str(args.font_dir/name),size)
        return cache[key]
    yy=np.linspace(0,1,HEIGHT)[:,None,None];xx=np.linspace(0,1,WIDTH)[None,:,None]
    glow=np.exp(-((xx-.77)**2+(yy-.32)**2)*7)
    background=Image.fromarray(np.clip(np.array([8,17,21])+glow*np.array([12,25,21]),0,255).astype(np.uint8))
    def panel(im,box,color=PANEL):
        ImageDraw.Draw(im).rounded_rectangle(box,radius=20,fill=color,outline=LINE,width=2)
    def block(im,box,value,size=30,color=INK,bold=False,mono=False):
        x,y,w,h=box;d=ImageDraw.Draw(im);f=font(size,bold,mono);lines=[]
        for para in value.split('\n'):
            if not para:lines.append('');continue
            line=''
            for word in para.split(' '):
                attempt=line+' '+word if line else word
                if d.textlength(attempt,font=f)>w:
                    if not line:raise ValueError('Unbreakable text exceeds box: '+word)
                    lines.append(line);line=word
                else:line=attempt
            lines.append(line)
        line_height=size+12
        if len(lines)*line_height>h:raise ValueError('Text exceeds vertical box: '+value)
        for n,line in enumerate(lines):d.text((x,y+n*line_height),line,font=f,fill=color)
        layout.append(dict(text=value,box=box,font=size,lines=len(lines)))
    def tag(im,x,y,label,color=GREEN):
        f=font(22,True);d=ImageDraw.Draw(im);w=round(d.textlength(label,font=f))+32
        panel(im,(x,y,x+w,y+44),(27,48,43));d.text((x+16,y+6),label,font=f,fill=color)
    def title(im,kicker,value,subtitle):
        tag(im,76,153,kicker)
        block(im,(76,218,1770,90),value,52,bold=True)
        block(im,(76,300,1770,100),subtitle,28,MUTED)
    def left(im,kicker,value,body):
        tag(im,76,172,kicker)
        block(im,(76,255,605,200),value,57,bold=True)
        block(im,(76,493,600,465),body,30,MUTED)
    def base(i,ref):
        im=background.copy();d=ImageDraw.Draw(im)
        block(im,(76,42,235,50),'CINEVERSE',31,GREEN,True)
        block(im,(322,47,850,40),'DEVELOPER WALKTHROUGH  /  APP 0.8.1',22,MUTED)
        block(im,(1390,47,455,40),'LOCAL PROCESSING  /  SBS',22,MUTED)
        d.line((76,110,1844,110),fill=LINE,width=2)
        block(im,(76,1027,900,34),f'{i+1:02}/{len(CHAPTERS):02}  {CHAPTERS[i][2].upper()}',19,MUTED)
        block(im,(1030,1027,815,34),ref,18,MUTED)
        return im
    def capture(name,box):return Image.open(args.captures/name).convert('RGB').crop(box)
    def put(im,shot,box):
        x,y,w,h=box;s=min(w/shot.width,h/shot.height)
        size=(round(shot.width*s),round(shot.height*s));pos=(x+(w-size[0])//2,y+(h-size[1])//2)
        panel(im,(pos[0]-2,pos[1]-2,pos[0]+size[0]+2,pos[1]+size[1]+2))
        im.paste(shot.resize(size,Image.Resampling.LANCZOS),pos)
    def arrow(im,start,end,color=GREEN):
        d=ImageDraw.Draw(im);d.line((*start,*end),fill=color,width=3)
        x,y=end;d.polygon(((x,y),(x-12,y-8),(x-12,y+8)),fill=color)
    def card(im,box,label,heading,body):
        x,y,w,h=box;panel(im,(x,y,x+w,y+h))
        block(im,(x+24,y+22,w-48,45),label,21,GREEN,True)
        block(im,(x+24,y+83,w-48,100),heading,32,bold=True)
        block(im,(x+24,y+198,w-48,h-213),body,26,MUTED)
    refs=[
        'Edited captures + recorded AI export / no new inference',
        'v0.8.1 / src-tauri/src/main.rs + worker/worker.py',
        'v0.8.1 / scripts/setup_engine.py + worker/hardware.py',
        'Recorded job request / paths omitted',
        'v0.8.1 / worker/pipeline.py + pinned iw3 engine',
        'Recorded iw3 flags / not a temporal-quality benchmark',
        'v0.8.1 / worker/protection.py + thermal/thermal_guard.py',
        'v0.8.1 / worker/pipeline.py / completed-stage evidence',
        'Original sample / examples/demo/generate_sample.py',
        'Recorded export / 240 frames / original 24 FPS',
        'Sanitized evidence / DEVELOPER-DEMO-EVIDENCE.json',
        'v0.8.1 hardware profiles / separate Mac 0.7 preview',
        'Application: MIT / engine and model licenses remain separate',
        'github.com/fernandohmachado8/CineVerse-Desktop',
    ]
    scenes=[]
    for i in range(len(CHAPTERS)):
        im=base(i,refs[i])
        if i==0:
            tag(im,76,198,'WORKING APP  /  ACTUAL 3D RESULT')
            block(im,(76,300,620,200),'A local stereo-\nvideo pipeline.',67,bold=True)
            block(im,(76,535,600,220),'Architecture, inference and verification.\n\nA developer view of CineVerse Desktop.',31,MUTED)
            tag(im,76,840,'REAL CAPTURES + RECORDED EVIDENCE')
        elif i==1:
            title(im,'ARCHITECTURE / EXPLANATORY DIAGRAM','Native host. Separate inference process.',
                  'The frontend requests work; backend checks and process ownership enforce the boundaries.')
            boxes=[(76,430,390,320),(536,430,390,320),(996,430,390,320),(1456,430,390,320)]
            for box,values in zip(boxes,[
                ('01 / REACT + TYPESCRIPT','User workflow','Settings, preview, capability-aware controls'),
                ('02 / TAURI + RUST','Native commands','JSON over child stdin; one active conversion job'),
                ('03 / PYTHON','Thermal supervisor','Owns conversion child; polls required sensors'),
                ('04 / ENGINES','PyTorch + FFmpeg','iw3 inference, encoding and verified publication')]):card(im,box,*values)
            for x in (478,938,1398):arrow(im,(x,575),(x+45,575))
            panel(im,(155,810,1775,940))
            block(im,(188,841,1554,70),"NDJSON events → Rust app.emit('conversion') → React progress / errors",31,GREEN)
        elif i==2:
            left(im,'SETUP / CAPABILITY CHECKS','Detect locally.\nProbe before use.',
                 'Private Python runtime, pinned engine code and model assets.\n\nRuntime/import and encoder checks precede a ready configuration.\n\nAutomatic can fall back to CPU. A tiny startup probe is not a sustained-load test.')
            put(im,capture('08-setup-private.jpg',(330,91,866,641)),(820,178,1000,760))
            block(im,(824,948,1000,35),'Actual settings crop; engine provisioned before capture.',22,MUTED)
        elif i==3:
            left(im,'REQUEST / ACTUAL RECORDED VALUES','Bound the job.\nValidate twice.',
                 'React submits an explicit preview request.\n\nThe backend probes media, resolves capabilities and checks storage.\n\nThe supervisor rechecks required temperatures before inference starts.')
            excerpt={k:request[k] for k in ('preview','previewStart','previewSeconds','strength','stereoMethod','fpsMode','processingBackend')}
            panel(im,(770,267,1840,845))
            tag(im,800,291,'NORMALIZED REQUEST / PATHS OMITTED')
            block(im,(800,375,1010,445),json.dumps(excerpt,indent=2),29,INK,mono=True)
        elif i==4:
            title(im,'STEREO / PIPELINE DIAGRAM','Relative depth becomes a synthesized viewpoint.',
                  'A horizontal image warp creates binocular disparity. It is not metric 3D reconstruction.')
            data=[('SOURCE FRAME','Preserve the left view','Prepared source imagery is re-encoded; it is not bit-identical video.'),
                  ('DEPTH ESTIMATION','Any_V2_S','Depth Anything V2 Small supplies relative depth, not measured metres.'),
                  ('REPROJECTION','forward_inpaint','iw3 maps depth to disparity and forward-reprojects the right view.'),
                  ('NEURAL FILLING','light_inpaint_v1','Newly exposed pixels are generated. Hidden detail is invented, not recovered.')]
            for n,values in enumerate(data):card(im,(76+n*460,426,390,420),*values)
            for x in (478,938,1398):arrow(im,(x,627),(x+45,627))
            tag(im,76,900,'RECORDED: DIVERGENCE 1.5 / CONVERGENCE 0.5 / DEPTH RESOLUTION 518')
        elif i==5:
            left(im,'TEMPORAL CONTROLS','Stabilization\nhas limits.',
                 'EMA normalization smooths depth scaling over time.\n\nScene-cut handling separates shots; edge dilation adjusts depth boundaries.\n\nThese controls aim to reduce instability. Hair, occlusions and motion can still fail.')
            panel(im,(770,270,1840,700))
            tag(im,800,297,'ACTUAL IW3 ARGUMENTS / ABRIDGED')
            block(im,(800,390,990,260),'--ema-normalize\n--ema-decay 0.75\n--scene-detect\n--edge-dilation 2',34,INK,mono=True)
            block(im,(800,780,990,165),'This continuous analytical sample has no scene cuts. It does not validate cut detection or difficult movie motion.',30,AMBER)
        elif i==6:
            left(im,'SUPERVISION / WINDOWS','Protection lives\noutside React.',
                 'The supervisor owns the converter process tree through a Windows job object.\n\nRequired sensor loss for 30 seconds stops the job. No automatic restart.\n\nOnly CPU sensing runs elevated. Software monitoring cannot guarantee safety.')
            for x,label,limit,detail in ((770,'CPU','95 °C / 10 s','100 °C immediate'),(1320,'GPU CORE','85 °C / 10 s','90 °C immediate')):
                panel(im,(x,265,x+520,486));block(im,(x+25,287,470,45),label,23,GREEN,True)
                block(im,(x+25,348,470,70),limit,40,bold=True)
                block(im,(x+25,421,470,45),detail,25,MUTED)
            put(im,capture('03-ready.jpg',(420,308,1175,545)),(770,552,1070,360))
            block(im,(790,939,1040,40),'Actual readiness capture; no thermal trip was induced.',23,MUTED)
        elif i==7:
            left(im,'RECOVERY / INTEGRITY','Reuse stages,\nnot assumptions.',
                 'Atomic checkpoints record stage outputs and SHA-256 hashes.\n\nResume checks source identity, settings, backend and pipeline version.\n\nCompleted verified stages can be reused. An interrupted stage restarts; resume is manual.')
            tag(im,770,216,'ACTUAL COMPLETED JOB / HASHES SHORTENED')
            for n,stage in enumerate(evidence['completedStages']):
                y=310+n*148;panel(im,(770,y,1840,y+122))
                block(im,(796,y+17,1000,45),stage['name'],29,bold=True)
                value=next(iter(stage['hashes'].values()))
                block(im,(796,y+72,1000,37),'SHA-256 '+value[:20]+'…  /  completed',23,GREEN,mono=True)
        elif i==8:
            title(im,'SOURCE / ORIGINAL ARTWORK','The original 2D sample',
                  '960 × 540 / 24 FPS / 10 seconds / SDR / no audio / analytically rendered, not AI reconstruction')
        elif i==9:
            title(im,'RESULT / ACTUAL RECORDED AI EXPORT','The source view and synthesized right-eye view',
                  'Depth 1.5 + Neural / Original FPS / H.264 NVENC / 1920 × 576 full SBS with compatibility margins')
            tag(im,80,363,'LEFT / SOURCE VIEW');tag(im,1000,363,'RIGHT / AI-SYNTHESIZED VIEW')
            block(im,(80,948,1770,44),'Use the separate SBS MP4 in VR. A flat presentation cannot show binocular depth.',27,GREEN)
        elif i==10:
            title(im,'VERIFICATION / MEASURED RESULTS','Check decoded output, not just encoder success.',
                  'The full reference and export timelines were decoded. These are functional checks, not a visual-quality score.')
            for box,value,label in [((76,438,350,180),'240','verified frames'),((460,438,350,180),'24 FPS','source cadence'),
                                   ((76,653,350,180),'0 ms','timestamp-grid error'),((460,653,350,180),'0','removed source pixels')]:
                x,y,w,h=box;panel(im,(x,y,x+w,y+h));block(im,(x+23,y+24,w-46,80),value,49,GREEN,True)
                block(im,(x+23,y+111,w-46,52),label,24,MUTED)
            report={'frames':validation['output']['frames'],'rate':validation['output']['rate'],
                    'width':validation['output']['width'],'height':validation['output']['height'],
                    'maxGridError':validation['output']['maxGridError'],'topBlackRows':18,'bottomBlackRows':18,
                    'sourceCheckPassed':validation['sourceCheckPassed'],'hasAudio':False}
            panel(im,(900,425,1840,935));tag(im,927,448,'RECORDED REPORT / SELECTED FIELDS')
            block(im,(927,524,885,415),json.dumps(report,indent=2),25,INK,mono=True)
            block(im,(76,875,755,100),'Source-eye MAE: 0.143–0.164 in 8-bit sample units versus prepared reference. Sampled encoding error, not perceptual quality.',24,MUTED)
        elif i==11:
            title(im,'CAPABILITY SCOPE / NOT ALL DEMONSTRATED','Optional branches are separate execution paths.',
                  'This sample demonstrates NVIDIA SDR at 24 FPS. It does not demonstrate HDR or frame interpolation.')
            rows=[('NVIDIA / CUDA','HDR10 + optional RIFE 60 FPS; NVENC','Implemented; not used in this sample. RTX 4090 physically tested.'),
                  ('WINDOWS / CPU','SDR, Original FPS; software H.264','Intel tested. Lower load budget and resolution; slower processing.'),
                  ('RADEON / EXPERIMENTAL','Allowlisted setup; SDR, Original FPS','Physical Radeon inference and sensor binding remain unverified.'),
                  ('MAC / SEPARATE 0.7','Apple Silicon; CPU default, opt-in MPS','Different preview build. Not demonstrated in this Windows video.')]
            for n,(a,b,c) in enumerate(rows):
                y=421+n*133;panel(im,(76,y,1844,y+112))
                block(im,(99,y+20,405,75),a,25,GREEN,True)
                block(im,(544,y+20,568,80),b,26)
                block(im,(1164,y+20,650,80),c,25,MUTED)
        elif i==12:
            title(im,'TRADEOFFS / ATTRIBUTION','Integration work with explicit boundaries.',
                  'CineVerse coordinates existing inference engines. It does not claim a newly trained stereo model.')
            for box,values in zip(((76,424,550,352),(687,424,550,352),(1298,424,550,352)),[
                ('SOURCE','File preserved','Prepared source-eye imagery is re-encoded. Movie timing is checked against the prepared reference.'),
                ('SYNTHESIS','Detail is inferred','The second-eye view, disoccluded texture and optional intermediate frames are AI-generated.'),
                ('LIMITS','Stereo on a screen','No walkable 360° world. Thin objects, reflections and motion can still produce artifacts.')]):card(im,box,*values)
            block(im,(76,835,1768,105),'Stereo: iw3 / nunif + Depth Anything V2. Optional interpolation: Practical-RIFE.\nCineVerse: desktop workflow, provisioning, process supervision, recovery and export verification.',28,GREEN)
        else:
            title(im,'SOURCE + REPRODUCTION','Inspect the code. Reproduce a short preview.',
                  'The 0.8.1 application source is pinned by release tag; this presentation reuses the recorded synthetic sample.')
            panel(im,(76,443,1844,710))
            block(im,(110,486,1688,90),'github.com/fernandohmachado8/CineVerse-Desktop',43,bold=True)
            block(im,(110,593,1688,70),'Start with docs/DEVELOPER_DEMO.md and the release evidence / model and engine licenses apply.',29,GREEN)
            block(im,(76,797,1768,135),'Recorded: 240-frame SDR/24 FPS conversion on RTX 4090 with CPU + GPU supervision.\nNot established: movie-wide visual quality, headset validation of this new sample, or broad GPU certification.',28,MUTED)
        scenes.append(im)
    def decode(path,w,h):
        data=subprocess.check_output([args.ffmpeg,'-v','error','-threads','2','-i',str(path),'-vf',f'scale={w}:{h}',
            '-frames:v','240','-pix_fmt','rgb24','-f','rawvideo','-threads','2','pipe:1'])
        frames=np.frombuffer(data,np.uint8).reshape(-1,h,w,3)
        assert len(frames)==240
        return frames
    original=decode(args.source,1120,630);stereo=decode(args.sbs,1760,528)
    def render(n):
        t=n/FPS;i=next(i for i,(a,b,_) in enumerate(CHAPTERS) if a<=t<b)
        start,end,_=CHAPTERS[i];local=t-start;im=scenes[i].copy()
        if i==0:im.paste(Image.fromarray(original[min(239,int(local*24))]),(740,283))
        if i==8:im.paste(Image.fromarray(original[min(239,int(local*24))]),(400,364))
        if i==9:im.paste(Image.fromarray(stereo[min(239,int(local*24))]),(80,412))
        d=ImageDraw.Draw(im);d.line((76,1008,1844,1008),fill=LINE,width=3)
        d.line((76,1008,76+round(1768*t/DURATION),1008),fill=GREEN,width=3)
        fade=min(1,local/.3,(end-t)/.25)
        return Image.blend(background,im,max(0,fade)) if fade<1 else im
    poster=render(3*FPS);draw=ImageDraw.Draw(poster)
    draw.ellipse((1230,516,1350,636),fill=GREEN,outline=INK,width=3)
    draw.polygon(((1278,546),(1278,606),(1320,576)),fill=(15,34,30))
    poster.save(args.output_dir/(STEM+'-Poster.jpg'),quality=92)
    # Every chapter's planned composition is saved locally for visual QA.
    for i,(a,b,_) in enumerate(CHAPTERS):render(round((a+b)/2*FPS)).save(args.output_dir/f'chapter-{i+1:02}.jpg',quality=90)
    command=[args.ffmpeg,'-v','error','-n','-f','rawvideo','-pix_fmt','rgb24','-s',f'{WIDTH}x{HEIGHT}','-r',str(FPS),
        '-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-threads','2','-crf','20','-pix_fmt','yuv420p',
        '-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-movflags','+faststart',
        '-metadata','title=CineVerse Desktop - Developer Walkthrough - Architecture, Inference and Verification',
        '-metadata','comment=Edited real app captures, explanatory diagrams and recorded AI sample; not a benchmark',str(output)]
    with subprocess.Popen(command,stdin=subprocess.PIPE) as child:
        for n in range(DURATION*FPS):
            child.stdin.write(render(n).tobytes())
            if n%(FPS*15)==0:print(f'Rendered {n//FPS}/{DURATION} seconds',flush=True)
        child.stdin.close()
        if child.wait():raise RuntimeError('Developer demo encoding failed')
    def stamp(s):return f'00:{int(s)//60:02}:{int(s)%60:02},000'
    subtitle='\n\n'.join(f'{i+1}\n{stamp(a)} --> {stamp(b)}\n{CAPTIONS[i]}' for i,(a,b,_) in enumerate(CHAPTERS))+'\n'
    (args.output_dir/(STEM+'.srt')).write_text(subtitle,encoding='utf8')
    record=dict(width=WIDTH,height=HEIGHT,fps=FPS,seconds=DURATION,frames=DURATION*FPS,chapters=CHAPTERS,
        sourceEvidenceSha256=hashlib.sha256(args.evidence.read_bytes()).hexdigest(),layoutBoxes=len(layout),
        layoutOverflow=False,inferenceStarted=False,sourceClipRate=24,presentationRateExplanation='30 FPS presentation repeats original 24 FPS samples; no interpolation',
        narration=False,music=False)
    (args.output_dir/'render-validation.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
    print('Developer presentation completed; inference was not started.')


if __name__=='__main__':main()
