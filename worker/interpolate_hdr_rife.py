"""Experimental FP32 PQ/BT.2020 RIFE -> 10-bit NVENC, before stereo synthesis.

No RGB8 conversion or SDR tone mapping. The model is not HDR-specific; motion
artifacts still require visual review. Original scene timing and audio retained.
"""
import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import av
import numpy as np
import torch
import torch.nn.functional as F

from hdr_trial import digest,hdr_params
from hdr_sei import add_static_hdr


def guarded_pair(left_time,right_time,rate,cuts):
    return round(left_time*rate) in cuts or round(right_time*rate) in cuts


def run(a):
    if a.output.exists():raise FileExistsError(a.output)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    raw=a.output.with_name(a.output.stem+'_raw.mp4')
    annotated=a.output.with_name(a.output.stem+'_hdr.mp4')
    if raw.exists() or annotated.exists():raise FileExistsError('Intermediate already exists')
    hdr_params(a.source,a.ffprobe)
    sys.path[:0]=[str(a.model.parent),str(a.rife_repo),str(a.iw3)]
    from train_log.IFNet_HDv3 import IFNet
    from model.pytorch_msssim import ssim_matlab
    from nunif.utils.video.color_transform import ColorTransform,OutputTransform
    from av.video.reformatter import Colorspace,ColorPrimaries,ColorTrc,ColorRange
    if not torch.cuda.is_available():raise RuntimeError('CUDA required')
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark=True
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    model=IFNet().cuda().float().eval()
    weights=torch.load(a.model/'flownet.pkl',map_location='cpu',weights_only=True)
    weights={k.removeprefix('module.'):v for k,v in weights.items()}
    model.load_state_dict({k:weights[k] for k in model.state_dict()},strict=True)
    cuts=set(json.loads(a.cuts.read_text(encoding='utf-8-sig'))['pts'])
    before=digest(a.source);began=time.perf_counter()
    ledger=[];generated=held_cut=held_edge=exact=0;extra_cuts=[];motion_checks=[];anchor_checks=[]
    peak_vram=0
    with av.open(str(a.source)) as src:
        vs=src.streams.video[0];source_rate=Fraction(vs.average_rate);w,h=vs.width,vs.height
        duration=Fraction(src.duration,av.time_base)
        if a.seconds is not None:duration=min(duration,Fraction(str(a.seconds)))
        count=math.ceil(duration*60)
        iterator=iter(src.decode(video=0));left=next(iterator);right=next(iterator,None)
        def tensor(frame):
            if frame.format.name!='yuv420p10le':raise ValueError('Requires decoded 10-bit HDR frames')
            return F.pad(ColorTransform.to_tensor(frame,device='cuda',dtype=torch.float32),
                         (0,(-w)%128,0,(-h)%128))
        lten=tensor(left);rten=tensor(right) if right else lten
        out_transform=OutputTransform('p010le',Colorspace.BT2020,ColorPrimaries.BT2020,ColorTrc.SMPTE2084,ColorRange.MPEG)
        checked_pair=None;is_cut=False
        with av.open(str(raw),'w') as dst:
            stream=dst.add_stream('hevc_nvenc',rate=60);stream.width=w;stream.height=h;stream.pix_fmt='p010le'
            stream.codec_context.colorspace=9;stream.codec_context.color_primaries=9
            stream.codec_context.color_trc=16;stream.codec_context.color_range=1
            stream.options={'preset':'p6','rc':'constqp','qp':'16','profile':'main10','gpu':'0'}
            with torch.inference_mode():
                for index in range(count):
                    t=Fraction(index,60)
                    while right is not None and t>=right.pts*right.time_base:
                        left,lten=right,rten;right=next(iterator,None)
                        if right is not None:rten=tensor(right)
                    lt=left.pts*left.time_base
                    if right is None or t<=lt:
                        prediction=lten;mode='source' if t==lt else 'edge-hold'
                        if mode=='source':exact+=1
                        else:held_edge+=1
                    else:
                        rt=right.pts*right.time_base;pair=(left.pts,right.pts)
                        if pair!=checked_pair:
                            is_cut=guarded_pair(lt,rt,source_rate,cuts)
                            if not is_cut:
                                small_l=F.interpolate(lten[:,:,:h,:w],(32,32),mode='bilinear',align_corners=False)
                                small_r=F.interpolate(rten[:,:,:h,:w],(32,32),mode='bilinear',align_corners=False)
                                is_cut=float(ssim_matlab(small_l,small_r))<.2
                                if is_cut:extra_cuts.append(round(rt*source_rate))
                            checked_pair=pair
                        if is_cut:
                            prediction=lten;mode='cut-hold';held_cut+=1
                        else:
                            # FP32, PQ-encoded RGB and BT.2020 gamut throughout. No autocast/RGB8 path.
                            prediction=model(torch.cat((lten,rten),1),float((t-lt)/(rt-lt)),[16,8,4,2,1])[2][-1]
                            if not bool(torch.isfinite(prediction).all()):raise RuntimeError(f'Nonfinite HDR interpolation at {index}')
                            mode='RIFE-FP32-HDR';generated+=1
                            if len(motion_checks)<24 and index%7==0:
                                motion_checks.append({'frame':index,'previousMAE':float((prediction-lten).abs().mean()),
                                    'nextMAE':float((prediction-rten).abs().mean())})
                    prediction=prediction[:,:,:h,:w].clamp(0,1).float()
                    frame=out_transform.from_cuda_tensor(prediction)
                    # Record luma codes before encoding for source/hold verification and brightness checks.
                    if mode!='RIFE-FP32-HDR' and (len(anchor_checks)<8 or mode=='cut-hold' and index%3==0):
                        anchor_checks.append({'frame':index,'sourcePTS':left.pts,'sourceTime':float(lt),'mode':mode})
                    frame.pts=index;frame.time_base=Fraction(1,60)
                    for p in stream.encode(frame):dst.mux(p)
                    ledger.append({'frame':index,'mode':mode,'sourcePTS':left.pts,'sourceTime':float(lt)})
                    if index%600==0:
                        peak_vram=max(peak_vram,torch.cuda.max_memory_allocated())
                        print(json.dumps({'frames':index,'total':count,'seconds':time.perf_counter()-began,'peakVRAMBytes':peak_vram}),flush=True)
                for p in stream.encode():dst.mux(p)
    sei=add_static_hdr(raw,a.source,annotated)
    command=[str(a.ffmpeg),'-v','error','-nostdin','-n','-i',str(annotated),'-i',str(a.source),
             '-map','0:v:0','-map','1:a:0?','-c','copy','-copyts','-avoid_negative_ts','disabled',
             '-tag:v','hvc1','-movflags','+faststart',*(['-t',str(a.seconds)] if a.seconds is not None else []),str(a.output)]
    subprocess.run(command,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert digest(a.source)==before
    assert hdr_params(a.output,a.ffprobe)==hdr_params(a.source,a.ffprobe)
    assert any(x['previousMAE']>1e-5 and x['nextMAE']>1e-5 for x in motion_checks),'No new motion detected'
    report={'source':str(a.source),'output':str(a.output),'sourceSha256':before,'sourceUnchanged':True,
        'frames':count,'fps':60,'sourceRate':str(source_rate),'sourceMediaDuration':float(duration),
        'roundingSeconds':count/60-float(duration),'generatedFrames':generated,'cutHeldFrames':held_cut,
        'edgeHeldFrames':held_edge,'exactFrames':exact,'extraSSIMCuts':extra_cuts,'motionChecks':motion_checks,
        'anchorChecks':anchor_checks,'seconds':time.perf_counter()-began,'weightsSha256':digest(a.model/'flownet.pkl'),
        'outputSha256':digest(a.output),'metadataRemux':sei,'precision':'FP32 HDR PQ/BT.2020 -> P010 NVENC Main10',
        'limitations':['RIFE weights are not specifically HDR-trained; new motion is experimental.',
                       'Blending is performed in nonlinear PQ code space; not a physically exact light integration.',
                       'Scene guards reduce cut mixing; occlusion/hair/hand artifacts still require visual review.']}
    a.output.with_suffix('.json').write_text(json.dumps(report,indent=2))
    a.output.with_suffix('.frames.json').write_text(json.dumps(ledger))
    print(json.dumps({k:report[k] for k in ('output','frames','generatedFrames','cutHeldFrames','seconds','roundingSeconds')}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','output','model','rife-repo','iw3','cuts','ffmpeg','ffprobe'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--seconds',type=float)
    run(p.parse_args())
