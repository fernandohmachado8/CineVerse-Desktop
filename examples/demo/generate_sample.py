"""Original animated geometry for a public demo; no external art or film footage.

The generated 2D source is analytical artwork, not an AI reconstruction. Run it
through CineVerse separately to obtain an actual AI-converted SBS result.
"""
import argparse
import math
from pathlib import Path
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def frame(t,width=960,height=540):
    yy=np.linspace(0,1,height,dtype=np.float32)[:,None,None]
    top=np.array([14,30,40]);bottom=np.array([39,67,72])
    background=np.broadcast_to(top*(1-yy)+bottom*yy,(height,width,3)).astype(np.uint8).copy()
    image=Image.fromarray(background);draw=ImageDraw.Draw(image)
    focal=width*.77;horizon=height*.43;camera=.16*math.sin(t*.6)
    def project(x,y,z):return (width/2+focal*(x-camera)/z,horizon-focal*(y-1.45)/z)
    draw.rectangle((0,horizon,width,height),fill=(27,43,47))
    for x in range(-10,11):draw.line([project(x,0,2),project(x,0,23)],fill=(60,83,85),width=1)
    for z in range(2,24):draw.line([project(-10,0,z),project(10,0,z)],fill=(60,83,85),width=1)
    # Far wall features are original geometry, not movie/book-derived scenery.
    for x in (-3.4,3.4):
        a=project(x-.5,2.6,13);b=project(x+.5,.2,13)
        draw.rounded_rectangle((a[0],a[1],b[0],b[1]),radius=12,fill=(39,70,77),outline=(80,111,115),width=2)
    objects=[(-1.35,.65,7.3,.65,(106,172,200)),(1.35,.83,5.8,.83,(216,158,96)),
        (.53*math.sin(t*.75),.68,3.8,.68,(157,208,173))]
    for x,y,z,r,color in objects:
        px,py=project(x,y,z);radius=focal*r/z
        sx,sy=project(x,0,z)
        draw.ellipse((sx-radius*.95,sy-radius*.18,sx+radius*.95,sy+radius*.18),fill=(14,24,27))
        left=int(px-radius);upper=int(py-radius);size=int(radius*2)+2
        gy,gx=np.mgrid[0:size,0:size].astype(np.float32)
        nx=(gx+left-px)/radius;ny=-(gy+upper-py)/radius;rr=nx*nx+ny*ny
        nz=np.sqrt(np.maximum(0,1-rr));light=np.clip(-.42*nx+.62*ny+.66*nz,0,1)
        brightness=.24+.70*light;specular=np.clip(-.36*nx+.54*ny+.76*nz,0,1)**28
        pixels=np.clip(np.array(color)[None,None,:]*brightness[:,:,None]+specular[:,:,None]*90,0,255).astype(np.uint8)
        sphere=Image.fromarray(pixels);mask=Image.fromarray(((rr<=1)*255).astype(np.uint8))
        image.paste(sphere,(left,upper),mask);draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((24,22,382,60),radius=12,fill=(11,23,30),outline=(69,97,96))
    font_path=Path('C:/Windows/Fonts/segoeui.ttf')
    font=ImageFont.truetype(str(font_path),17) if font_path.exists() else ImageFont.load_default()
    draw.text((39,31),'ORIGINAL SYNTHETIC SAMPLE  /  2D SOURCE',font=font,fill=(204,226,216))
    return image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ffmpeg',default='ffmpeg')
    parser.add_argument('--seconds',type=int,default=10)
    parser.add_argument('--fps',type=int,default=24)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('Preserving existing sample: '+str(args.output))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    command=[args.ffmpeg,'-v','error','-n','-f','rawvideo','-pix_fmt','rgb24','-s','960x540','-r',str(args.fps),
        '-i','pipe:0','-an','-c:v','libx264','-threads','2','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',
        '-metadata','comment=Original analytical animation; not film footage or AI reconstruction',str(args.output)]
    with subprocess.Popen(command,stdin=subprocess.PIPE) as child:
        for n in range(args.seconds*args.fps):child.stdin.write(frame(n/args.fps).tobytes())
        child.stdin.close()
        if child.wait():raise RuntimeError('Sample encoding failed')
    print('Generated original 2D sample; no AI conversion was performed by this generator.')


if __name__=='__main__':main()
