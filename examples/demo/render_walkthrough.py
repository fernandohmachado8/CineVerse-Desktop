"""Edit real app captures and actual sample exports into a captioned product demo.

No app UI, progress, sensor reading or stereo result is fabricated here. Captures
must come from the real 0.8.1 app using the original public sample. Private setup
paths are excluded by explicit crops. This is an edited walkthrough, not a live
screencast or a benchmark. Requires NumPy, Pillow and FFmpeg.
"""
import argparse
import math
from pathlib import Path
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W,H,FPS,DURATION=1920,1080,30,86
INK=(232,241,235);MUTED=(164,187,181);GREEN=(174,215,184);LINE=(54,79,73)
CHAPTERS=[(0,6,'CineVerse Desktop'),(6,16,'Install the engine'),(16,25,'Choose a video'),
    (25,35,'Depth and motion'),(35,44,'Protection and preview'),(44,54,'Original 2D source'),
    (54,66,'Actual AI SBS output'),(66,75,'Open the export'),(75,86,'Watch in VR')]
CAPTIONS=[
    'CineVerse Desktop turns local 2D video into SBS 3D for VR playback.',
    'Install the app, then use Automatic engine setup. The engine was installed before this demo.',
    'Choose a local video and an output folder. Your source stays untouched.',
    'Start at depth 1.5, Neural filling and Original FPS. Preview before increasing depth.',
    'Wait for live required temperatures, then generate a short preview. Processing is condensed here.',
    'This original 10-second animation is our 2D source. It contains no movie footage or audio.',
    'This is the actual AI-converted SBS result at depth 1.5 and 24 FPS. Use the separate file in VR.',
    'The app checked 240 frames. Open the output folder and load the SBS MP4 in your VR player.',
    'In Bigscreen choose SBS, left eye first. Download the app, tutorial and separate sample on GitHub.'
]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--captures',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--sbs',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--ffmpeg',default='ffmpeg')
    p.add_argument('--font-dir',type=Path,default=Path('C:/Windows/Fonts'))
    args=p.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    out=args.output_dir/'CineVerse-Desktop-Demo-0.8.1.mp4'
    if out.exists():raise FileExistsError('Preserving existing demo: '+str(out))
    fonts={}
    def font(size,bold=False):
        key=(size,bold)
        if key not in fonts:
            path=args.font_dir/('segoeuib.ttf' if bold else 'segoeui.ttf')
            fonts[key]=ImageFont.truetype(str(path),size)
        return fonts[key]
    yy=np.linspace(0,1,H)[:,None,None];xx=np.linspace(0,1,W)[None,:,None]
    glow=np.exp(-((xx-.8)**2+(yy-.35)**2)*6)
    bg=np.clip(np.array([8,17,21])[None,None,:]+glow*np.array([12,27,21]),0,255)
    background=Image.fromarray(np.broadcast_to(bg,(H,W,3)).astype(np.uint8))
    def text(im,xy,value,size=30,color=INK,bold=False):
        d=ImageDraw.Draw(im);f=font(size,bold)
        for n,line in enumerate(value.split('\n')):
            if d.textbbox((0,0),line,font=f)[2]+xy[0]>W-55:raise ValueError('Text overflow: '+line)
            d.text((xy[0],xy[1]+n*(size+13)),line,font=f,fill=color)
    def pill(im,xy,label):
        d=ImageDraw.Draw(im);f=font(22,True);box=d.textbbox((0,0),label,font=f)
        d.rounded_rectangle((xy[0],xy[1],xy[0]+box[2]+34,xy[1]+43),radius=14,fill=(27,49,43),outline=LINE)
        d.text((xy[0]+17,xy[1]+6),label,font=f,fill=GREEN)
    def base(index):
        im=background.copy();d=ImageDraw.Draw(im)
        d.line((72,111,W-72,111),fill=LINE,width=2)
        text(im,(72,43),'CINEVERSE',31,GREEN,True)
        text(im,(310,49),'DESKTOP  /  PUBLIC PREVIEW 0.8.1',22,MUTED)
        text(im,(1355,49),'LOCAL PROCESSING  ·  SBS 3D',22,MUTED)
        text(im,(72,1023),f'{index+1:02d} / {len(CHAPTERS):02d}   {CHAPTERS[index][2].upper()}',21,MUTED)
        text(im,(1095,1023),'EDITED WALKTHROUGH  ·  ORIGINAL SAMPLE ART',20,MUTED)
        return im
    def capture(name,crop):return Image.open(args.captures/name).convert('RGB').crop(crop)
    def put(im,shot,box):
        x,y,mw,mh=box;scale=min(mw/shot.width,mh/shot.height)
        size=(round(shot.width*scale),round(shot.height*scale));pos=(x+(mw-size[0])//2,y+(mh-size[1])//2)
        d=ImageDraw.Draw(im);d.rounded_rectangle((pos[0]-2,pos[1]-2,pos[0]+size[0]+2,pos[1]+size[1]+2),radius=10,fill=LINE)
        im.paste(shot.resize(size,Image.Resampling.LANCZOS),pos)
    def left(im,number,title,body):
        pill(im,(72,180),number)
        text(im,(72,267),title,57,INK,True)
        text(im,(72,490),body,28,MUTED)
    shots={
        'source':capture('01-source.jpg',(0,32,1205,890)),
        'setup':capture('08-setup-private.jpg',(330,91,866,641)),
        'controls':capture('02-controls.jpg',(48,158,380,547)),
        'ready':capture('03-ready.jpg',(420,308,1175,545)),
        'started':capture('04-started.jpg',(420,562,1175,752)),
        'done':capture('06-complete.jpg',(420,551,1175,802)),
    }
    scenes=[]
    for i in range(len(CHAPTERS)):
        im=base(i)
        if i==0:
            pill(im,(72,217),'2D VIDEO  →  SBS 3D')
            text(im,(72,312),'Bring depth\nto movie night.',66,INK,True)
            text(im,(72,522),'Your local video.\nA new view in your VR cinema.',30,MUTED)
            pill(im,(72,693),'WORKING APP  /  ACTUAL 3D RESULT')
            text(im,(72,780),'Captioned quick start\nWindows 0.8.1 public preview',25,MUTED)
        elif i==1:
            left(im,'01  /  SET UP','Automatic setup.\nFewer steps.',
                 'Install the app, then open\nEngine settings. Keep Automatic.\n\nChoose a drive, acknowledge\nthe downloads and install.\n\nAllow several GB and time\nfor the first download.')
            put(im,shots['setup'],(835,151,950,775))
            text(im,(865,945),'Actual settings · engine already installed for this demo',22,MUTED)
        elif i==2:
            left(im,'02  /  CHOOSE','Start with\nyour own video.',
                 'Drop a file, browse, or paste\na local video path.\n\nChoose a separate output folder.\nYour source stays untouched.\n\nThis demo uses original artwork,\nnot copyrighted movie footage.')
            put(im,shots['source'],(670,153,1180,813))
        elif i==3:
            left(im,'03  /  ADJUST','Depth you\ncan control.',
                 'Begin with 1.5 + Neural.\nPreview before adding more depth.\n\nOriginal FPS keeps the cadence.\nOptional 60 FPS smoothing\nis available on supported NVIDIA.\n\nThis sample uses 24 FPS.')
            put(im,shots['controls'],(770,200,600,700))
            pill(im,(1390,305),'DEPTH 1.5')
            text(im,(1390,405),'Neural filling\ngenerates missing\nregions. Artifacts\ncan still occur.',27,MUTED)
        elif i==4:
            left(im,'04  /  PREVIEW','Check. Preview.\nThen decide.',
                 'Wait for live CPU + GPU readings.\nStart a short preview.\n\nJobs expose their current stage,\nprogress and cancellation.\n\nProcessing is condensed here.\nNot a speed benchmark.')
            put(im,shots['ready'],(725,214,1125,380))
            put(im,shots['started'],(725,649,1125,290))
        elif i==5:
            text(im,(72,150),'The original 2D source',48,INK,True)
            text(im,(72,219),'Original analytical animation · 10 seconds · 24 FPS · SDR · no audio',26,MUTED)
        elif i==6:
            text(im,(72,150),'The actual AI-converted SBS result',48,INK,True)
            text(im,(72,219),'Depth 1.5 · Neural gap filling · Original FPS · full SBS · compatibility margins',26,MUTED)
            pill(im,(80,310),'LEFT EYE / SOURCE VIEW')
            pill(im,(1000,310),'RIGHT EYE / AI-SYNTHESIZED VIEW')
            text(im,(80,935),'Download the separate SBS file. A flat screen cannot show binocular depth.',30,GREEN)
        elif i==7:
            left(im,'05  /  EXPORT','Your stereo\nvideo is ready.',
                 'The app checked 240 frames\nat the original 24 FPS.\n\nOpen output folder.\nLoad the MP4 in your VR player.\n\nTry a preview before\nprocessing a long video.')
            put(im,shots['done'],(725,320,1125,470))
            text(im,(812,850),'ACTUAL COMPLETED PREVIEW · NO FULL MOVIE JOB',23,GREEN,True)
        else:
            text(im,(72,170),'Ready for your VR cinema.',63,INK,True)
            text(im,(72,285),'In Bigscreen: SBS · left eye first · check the aspect ratio.',32,GREEN)
            d=ImageDraw.Draw(im)
            for x,label in ((75,'01   DOWNLOAD'),(675,'02   TRY A PREVIEW'),(1275,'03   WATCH IN VR')):
                d.rounded_rectangle((x,402,x+555,635),radius=24,fill=(22,39,38),outline=LINE,width=2)
                text(im,(x+28,443),label,26,GREEN,True)
            text(im,(103,506),'Windows public preview\nApple Silicon: separate 0.7',26,MUTED)
            text(im,(703,506),'Original + actual SBS sample\nTutorial + source on GitHub',26,MUTED)
            text(im,(1303,506),'Stereo depth on a screen\nNo walkable 360° world',26,MUTED)
            text(im,(72,725),'github.com/fernandohmachado8/CineVerse-Desktop',36,INK,True)
            text(im,(72,820),'Powered by iw3 / nunif + Depth Anything V2 · Optional smoothing: Practical-RIFE',25,MUTED)
            text(im,(72,880),'Original artwork · No film footage or music · Third-party licenses apply',24,MUTED)
        scenes.append(im)
    def decode(path,width,height):
        cmd=[args.ffmpeg,'-v','error','-threads','2','-i',str(path),'-vf',f'scale={width}:{height}',
             '-frames:v','240','-pix_fmt','rgb24','-f','rawvideo','-threads','2','pipe:1']
        raw=subprocess.check_output(cmd)
        frames=np.frombuffer(raw,np.uint8).reshape(-1,height,width,3)
        if len(frames)!=240:raise ValueError('Expected 240 real sample frames')
        return frames
    original=decode(args.source,1120,630)
    stereo=decode(args.sbs,1760,528)
    # The source's motion is never interpolated or retimed: video playback uses
    # nearest source frames on the presentation's 30 FPS timeline.
    def render(n):
        t=n/FPS;i=next(i for i,(a,b,_) in enumerate(CHAPTERS) if a<=t<b)
        start,end,_=CHAPTERS[i];local=t-start;im=scenes[i].copy()
        if i==0:im.paste(Image.fromarray(original[min(239,int(local*24))]),(740,278))
        if i==5:im.paste(Image.fromarray(original[min(239,int(local*24))]),(400,319))
        if i==6:im.paste(Image.fromarray(stereo[min(239,int(local*24))]),(80,389))
        d=ImageDraw.Draw(im);d.line((72,995,1848,995),fill=LINE,width=3)
        d.line((72,995,72+round(1776*t/DURATION),995),fill=GREEN,width=3)
        fade=min(1,local/.30,(end-t)/.25)
        if fade<1:im=Image.blend(background,im,max(0,fade))
        return im
    # A frame from the actual walkthrough, with a play badge, becomes the poster.
    poster=render(3*FPS);d=ImageDraw.Draw(poster)
    d.ellipse((1230,510,1350,630),fill=(181,216,189),outline=(232,241,235),width=3)
    d.polygon(((1278,540),(1278,600),(1320,570)),fill=(15,34,30))
    poster.save(args.output_dir/'CineVerse-Demo-Poster.jpg',quality=92)
    cmd=[args.ffmpeg,'-v','error','-n','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),
         '-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-threads','2','-crf','20','-pix_fmt','yuv420p',
         '-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-movflags','+faststart',
         '-metadata','title=CineVerse Desktop 0.8.1 - Demo and Quick Start',
         '-metadata','comment=Edited real app captures; original sample; actual AI SBS export; not a benchmark',str(out)]
    with subprocess.Popen(cmd,stdin=subprocess.PIPE) as child:
        for n in range(DURATION*FPS):
            frame=render(n);child.stdin.write(frame.tobytes())
            if n%(FPS*10)==0:print(f'Rendered {n//FPS}/{DURATION} seconds',flush=True)
        child.stdin.close()
        if child.wait():raise RuntimeError('Walkthrough encoding failed')
    def stamp(seconds):return f'00:{int(seconds)//60:02}:{int(seconds)%60:02},000'
    srt='\n\n'.join(f'{i+1}\n{stamp(a)} --> {stamp(b)}\n{CAPTIONS[i]}' for i,(a,b,_) in enumerate(CHAPTERS))+'\n'
    (args.output_dir/'CineVerse-Desktop-Demo-0.8.1.srt').write_text(srt,encoding='utf8')
    print('Finished edited walkthrough; no app states or stereo views fabricated.')


if __name__=='__main__':main()
