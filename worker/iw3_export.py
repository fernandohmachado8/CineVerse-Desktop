"""Process-local adapter: add initialized compatibility margins before encoding.

No changes to the installed iw3 checkout or the original image area.
"""
import runpy
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path.cwd()))
import torch
import torch.nn.functional as F
from nunif.utils.video.color_transform import OutputTransform

original=OutputTransform.transform


def transform(self,x):
    if torch.is_tensor(x):
        height=x.shape[-2]
        aligned=((height+16+63)//64)*64
        top=((aligned-height)//4)*2
        x=F.pad(x,(0,0,top,aligned-height-top),value=0)
    else:
        raise ValueError('Compatibility export expects the iw3 floating-point image path')
    return original(self,x)


OutputTransform.transform=transform
sys.argv=['iw3',*sys.argv[1:]]
if os.environ.get('CINEVERSE_PROCESSING_BACKEND') == 'cpu':
    # Call the CLI function directly: iw3's module entry probes CUDA contexts
    # before parsing --gpu, even for a CPU request.
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    from iw3.cli import main
    main()
else:
    runpy.run_module('iw3',run_name='__main__')
