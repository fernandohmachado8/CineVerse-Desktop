"""Original analytical scene fixture. No film, AI model or external art is used."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def scene(width, height, t, eye=0):
    im=Image.new('RGB',(width,height),(14,23,29)); draw=ImageDraw.Draw(im)
    focal=width*.8; cx=width/2; cy=height*.44; camera_x=eye*.065
    def project(x,y,z):return (cx+focal*(x-camera_x)/z,cy-focal*(y-1.5)/z)
    draw.rectangle((0,cy,width,height),fill=(24,39,43))
    for x in range(-8,9):draw.line([project(x,0,2),project(x,0,18)],fill=(54,79,81),width=1)
    for z in range(2,19):draw.line([project(-8,0,z),project(8,0,z)],fill=(54,79,81),width=1)
    for x,y,z,r,color in [(-1.7,.9,8,.7,(103,154,184)),(1.4,1.2,5,.8,(198,148,89)),(.55*math.sin(t*1.4),.85,3.2,.6,(155,207,174))]:
        px,py=project(x,y,z);radius=focal*r/z
        draw.ellipse((px-radius,py-radius,px+radius,py+radius),fill=color)
        draw.arc((px-radius,py-radius,px+radius,py+radius),190,310,fill=(227,239,230),width=2)
    draw.rectangle((0,0,width,28),fill=(9,17,23))
    draw.text((12,9),'SYNTHETIC FIXTURE / '+('LEFT EYE' if eye<0 else 'RIGHT EYE' if eye>0 else 'SOURCE'),fill=(198,222,210))
    return im


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets',type=Path,default=ROOT/'docs/assets')
    parser.add_argument('--video',type=Path,help='Optional synthetic 2D MP4, for local conversion tests only')
    parser.add_argument('--ffmpeg',default='ffmpeg')
    args=parser.parse_args();args.assets.mkdir(parents=True,exist_ok=True)
    frames=[]
    for n in range(24):
        canvas=Image.new('RGB',(960,300),(10,18,22))
        canvas.paste(scene(480,270,n/8,-.5),(0,0));canvas.paste(scene(480,270,n/8,.5),(480,0))
        ImageDraw.Draw(canvas).text((12,281),'Analytical SBS test geometry - NOT an AI conversion or movie reconstruction',fill=(170,195,181))
        frames.append(canvas)
    frames[0].save(args.assets/'synthetic-preview.gif',save_all=True,append_images=frames[1:],duration=125,loop=0,optimize=True)
    scene(960,540,0).save(args.assets/'synthetic-frame.png')
    provenance=args.assets/'provenance.json'
    assets=json.loads(provenance.read_text(encoding='utf8'))['assets'] if provenance.is_file() else {}
    for name in ['synthetic-preview.gif','synthetic-frame.png']:
        file=args.assets/name
        assets[name]={'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'source':'examples/generate_fixture.py','content':'original analytical geometry; not AI output or film footage','license':'MIT'}
    (args.assets/'provenance.json').write_text(json.dumps({'assets':assets},indent=2)+'\n',encoding='utf8')
    if args.video:
        if args.video.exists():raise FileExistsError(args.video)
        args.video.parent.mkdir(parents=True,exist_ok=True)
        command=[args.ffmpeg,'-v','error','-n','-f','rawvideo','-pix_fmt','rgb24','-s','960x540','-r','24','-i','pipe:0','-an','-c:v','libx264','-pix_fmt','yuv420p',str(args.video)]
        with subprocess.Popen(command,stdin=subprocess.PIPE) as child:
            for n in range(240):child.stdin.write(scene(960,540,n/24).tobytes())
            child.stdin.close()
            if child.wait():raise RuntimeError('Synthetic fixture encode failed')
    print('Original synthetic assets generated; no media or models downloaded.')


if __name__=='__main__':main()
