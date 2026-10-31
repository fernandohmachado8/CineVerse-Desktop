"""Process-local compatibility for the pinned iw3 deterministic forward warp.

MPS rejects its int64 scatter_reduce_ even with automatic fallback enabled.
Delegate this one indexing operation to upstream's unchanged CPU function;
never cast ordering indices to float or patch torch globally.
"""
import functools
import sys
import torch


def install():
    from iw3 import forward_warp
    original=forward_warp.ordered_index_copy

    @functools.wraps(original)
    def ordered_copy(c,src_index,dest_index,index_order,undefined_value=-1):
        if c.device.type!='mps':
            return original(c,src_index,dest_index,index_order,undefined_value=undefined_value)
        fill=undefined_value.cpu() if torch.is_tensor(undefined_value) else undefined_value
        result=original(c.cpu(),src_index.cpu(),dest_index.cpu(),index_order.cpu(),undefined_value=fill)
        return result.to(c.device)

    forward_warp.ordered_index_copy=ordered_copy
    print('CineVerse MPS: deterministic forward-warp index copies run on CPU (int64 scatter_reduce_ compatibility); model inference still requests MPS.',file=sys.stderr,flush=True)
