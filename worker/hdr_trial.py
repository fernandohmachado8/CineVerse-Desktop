"""Shared HDR10 metadata validation for the desktop engine."""
from fractions import Fraction
import hashlib
import json
import subprocess


def digest(path):
    with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def hdr_params(path,ffprobe,stream_index=None):
    data=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-select_streams',str(stream_index) if stream_index is not None else 'v:0',
        '-read_intervals','%+#1','-show_frames','-show_streams','-of','json',str(path)],
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
    v=data['streams'][0]
    if v.get('pix_fmt') not in ('yuv420p10le','yuv422p10le','yuv444p10le','yuv420p12le','yuv422p12le','yuv444p12le'):
        raise ValueError('HDR requires a decoded 10-bit or higher source.')
    if (v.get('color_primaries'),v.get('color_transfer'),v.get('color_space'))!=('bt2020','smpte2084','bt2020nc'):
        raise ValueError('HDR10 must use BT.2020/PQ. HLG is not supported in this build.')
    params=['hdr10=1','no-hdr10-opt=1','no-dhdr10-opt=1','repeat-headers=1']
    for s in data['frames'][0].get('side_data_list',[]):
        if s['side_data_type']=='Mastering display metadata':
            xy=lambda k:round(Fraction(s[k])*50000)
            lum=lambda k:round(Fraction(s[k])*10000)
            params.append(f"master-display=G({xy('green_x')},{xy('green_y')})B({xy('blue_x')},{xy('blue_y')})R({xy('red_x')},{xy('red_y')})WP({xy('white_point_x')},{xy('white_point_y')})L({lum('max_luminance')},{lum('min_luminance')})")
        if s['side_data_type']=='Content light level metadata':params.append(f"max-cll={s['max_content']},{s['max_average']}")
    return params
