"""Timestamp-driven RIFE 4.25 interpolation, with cut guards and unchanged audio.

Uses an external official Practical-RIFE checkout and official model download.
No model or media is bundled. Output is a new experimental 2D reference.
"""
import argparse
from fractions import Fraction
import hashlib
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


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main(a):
    if a.output.exists():
        raise FileExistsError(a.output)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    silent = a.output.with_name(a.output.stem + '_video.mp4')
    if silent.exists():
        raise FileExistsError(silent)
    sys.path[:0] = [str(a.model.parent), str(a.rife_repo)]
    from train_log.IFNet_HDv3 import IFNet
    from model.pytorch_msssim import ssim_matlab

    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = True
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA required for this experimental runner')
    model = IFNet().cuda().eval()
    weights = torch.load(a.model / 'flownet.pkl', map_location='cpu', weights_only=True)
    weights = {k.removeprefix('module.'): v for k, v in weights.items()}
    # The official checkpoint also contains training-only teacher/caltime weights.
    # Strictly require all inference-network keys and shapes.
    model.load_state_dict({k: weights[k] for k in model.state_dict()}, strict=True)
    cuts_json = json.loads(a.cuts.read_text(encoding='utf-8-sig'))
    cuts = set(cuts_json['pts'])
    before = sha(a.source)
    started = time.perf_counter()
    with av.open(str(a.source)) as src:
        vs = src.streams.video[0]
        source_rate = Fraction(vs.average_rate)
        w, h = vs.width, vs.height
        duration = Fraction(src.duration, av.time_base)
        if a.seconds is not None:
            duration = min(duration, Fraction(str(a.seconds)))
        count = math.ceil(duration * a.fps)
        iterator = iter(src.decode(video=0))
        left = next(iterator)
        right = next(iterator, None)
        left_rgb = left.to_ndarray(format='rgb24')
        right_rgb = right.to_ndarray(format='rgb24') if right else left_rgb
        pad = (0, (-w) % 128, 0, (-h) % 128)

        def tensor(rgb):
            x = torch.from_numpy(rgb.copy()).permute(2, 0, 1)[None].cuda().float() / 255
            return F.pad(x, pad)

        lten, rten = tensor(left_rgb), tensor(right_rgb)
        checked_pair = None
        is_cut = False
        extra_cuts = []
        generated = held_cut = held_edge = exact = 0
        examples = []
        with av.open(str(silent), 'w') as out:
            stream = out.add_stream('libx264', rate=a.fps)
            stream.width, stream.height = w, h
            stream.pix_fmt = 'yuv420p'
            stream.options = {'crf': '14', 'preset': 'fast', 'threads': '4'}
            with torch.inference_mode():
                for index in range(count):
                    t = Fraction(index, a.fps)
                    while right is not None and t >= right.pts * right.time_base:
                        left, left_rgb, lten = right, right_rgb, rten
                        right = next(iterator, None)
                        if right is not None:
                            right_rgb = right.to_ndarray(format='rgb24')
                            rten = tensor(right_rgb)
                    lt = left.pts * left.time_base
                    if right is None or t <= lt:
                        rgb = left_rgb
                        if t == lt:
                            exact += 1
                        else:
                            held_edge += 1
                        mode = 'source/edge-hold'
                    else:
                        rt = right.pts * right.time_base
                        pair = (left.pts, right.pts)
                        if pair != checked_pair:
                            # iw3 scene-cache PTS are ticks at its output frame rate.
                            right_tick = round(rt * source_rate)
                            left_tick = round(lt * source_rate)
                            # iw3 marks the END of a shot, not the next shot's start.
                            # Guard both adjacent intervals conservatively.
                            is_cut = left_tick in cuts or right_tick in cuts
                            if not is_cut:
                                small_l = F.interpolate(lten[:, :, :h, :w], (32, 32), mode='bilinear', align_corners=False)
                                small_r = F.interpolate(rten[:, :, :h, :w], (32, 32), mode='bilinear', align_corners=False)
                                is_cut = float(ssim_matlab(small_l, small_r)) < .2
                                if is_cut:
                                    extra_cuts.append(right_tick)
                            checked_pair = pair
                        if is_cut:
                            rgb = left_rgb
                            held_cut += 1
                            mode = 'cut-hold'
                        else:
                            fraction = float((t - lt) / (rt - lt))
                            with torch.autocast('cuda', dtype=torch.float16):
                                prediction = model(torch.cat((lten, rten), 1), fraction, [16, 8, 4, 2, 1])[2][-1]
                            if not bool(torch.isfinite(prediction).all()):
                                raise RuntimeError(f'Nonfinite RIFE output at {index}')
                            rgb = prediction[0, :, :h, :w].clamp(0, 1).mul(255).round().byte().permute(1, 2, 0).cpu().numpy()
                            generated += 1
                            mode = 'RIFE'
                    frame = av.VideoFrame.from_ndarray(rgb, format='rgb24')
                    frame.pts, frame.time_base = index, Fraction(1, a.fps)
                    for packet in stream.encode(frame):
                        out.mux(packet)
                    if len(examples) < 20:
                        examples.append({'frame': index, 'time': float(t), 'mode': mode})
                    if index % 60 == 0:
                        print(json.dumps({'frames': index, 'total': count, 'seconds': round(time.perf_counter() - started, 1)}), flush=True)
                for packet in stream.encode():
                    out.mux(packet)
    subprocess.run([str(a.ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
                    '-i', str(silent), '-i', str(a.source), '-map', '0:v:0', '-map', '1:a:0?',
                    '-c', 'copy', '-bsf:v', 'h264_metadata=video_full_range_flag=0:colour_primaries=1:transfer_characteristics=1:matrix_coefficients=6',
                    '-color_range', 'tv', '-colorspace', 'smpte170m', '-color_primaries', 'bt709', '-color_trc', 'bt709',
                    '-movflags', '+faststart',
                    *(['-t', str(a.seconds)] if a.seconds is not None else []), str(a.output)], check=True)
    report = {'source': str(a.source), 'output': str(a.output), 'sourceSha256': before,
              'sourceUnchanged': sha(a.source) == before, 'outputSha256': sha(a.output),
              'model': 'official Practical-RIFE 4.25', 'weightsSha256': sha(a.model / 'flownet.pkl'),
              'rifeCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=a.rife_repo, text=True).strip(),
              'gpu': torch.cuda.get_device_name(), 'torch': torch.__version__,
              'frames': count, 'fps': a.fps, 'sourceMediaDuration': float(duration),
              'outputVideoDuration': count / a.fps, 'durationRoundingSeconds': count / a.fps - float(duration),
              'generatedFrames': generated, 'cutHeldFrames': held_cut, 'edgeHeldFrames': held_edge,
              'exactSourceFrames': exact, 'detectedCuts': len(cuts), 'extraSSIMCuts': extra_cuts,
              'examples': examples, 'seconds': time.perf_counter() - started,
              'note': 'New motion is synthesized before stereo conversion. Hard cuts hold preceding image until next original shot timestamp. No interpolation across guarded cuts. Cut timing is quantized to the 60Hz output grid.'}
    a.output.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    if not report['sourceUnchanged']:
        raise RuntimeError('Source changed')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ['source', 'output', 'model', 'rife-repo', 'cuts', 'ffmpeg']:
        p.add_argument('--' + key, type=Path, required=True)
    p.add_argument('--fps', type=int, default=60)
    p.add_argument('--seconds', type=float)
    main(p.parse_args())
