"""Tiny startup checks, not a video conversion or performance certification."""
import argparse
import json
import contextlib
import sys
from pathlib import Path
import torch
import torchvision


def run(backend,repo=None):
    torch.set_num_threads(2)
    hip=bool(torch.version.hip)
    if backend=='cuda' and hip:raise ValueError('AMD HIP is not an NVIDIA runtime.')
    if backend=='rocm' and not hip:raise ValueError('The installed runtime is not AMD ROCm.')
    device='cpu'
    result=dict(backend=backend,torch=torch.__version__,torchvision=torchvision.__version__,hip=torch.version.hip)
    if repo:
        sys.path.insert(0,str(Path(repo).resolve()))
        with contextlib.redirect_stdout(sys.stderr):
            from iw3.cli import main
        result['iw3ImportPassed']=callable(main)
    if backend in ('cuda','rocm'):
        if not torch.cuda.is_available():raise ValueError('The GPU runtime could not initialize; no conversion was started.')
        if backend=='rocm' and torch.cuda.device_count()!=1:raise ValueError('The AMD runtime does not expose exactly one GPU.')
        device='cuda:0';result['gpuName']=torch.cuda.get_device_name(0)
        result['architecture']=getattr(torch.cuda.get_device_properties(0),'gcnArchName','').split(':')[0]
    # Exercise inference, interpolation and ordered integer reduction on tiny data.
    with torch.inference_mode():
        layer=torch.nn.Conv2d(3,4,3).to(device)
        output=layer(torch.ones(1,3,16,16,device=device))
        resized=torch.nn.functional.interpolate(output,size=(8,8),mode='bilinear',align_corners=False)
        dest=torch.full((4,),-1,dtype=torch.long,device=device)
        dest.scatter_reduce_(0,torch.tensor([1,1,2],device=device),torch.tensor([0,1,2],device=device),reduce='amax',include_self=False)
        if not torch.isfinite(resized).all().item() or dest.cpu().tolist()!=[-1,1,2,-1]:raise ValueError('The tiny runtime operation checks failed.')
    if device!='cpu':torch.cuda.synchronize()
    print(json.dumps(dict(result,ready=True)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--backend',choices=['cpu','cuda','rocm'],required=True)
    parser.add_argument('--iw3-repo')
    args=parser.parse_args()
    try:run(args.backend,args.iw3_repo)
    except Exception as error:
        print(json.dumps(dict(ready=False,backend=args.backend,error=str(error))),flush=True);raise SystemExit(1)
