"""Explicit source compatibility and audio mapping for local imports.

An HDR10-compatible Dolby Vision base is an HDR10 input option, never Dolby
Vision preservation. Unknown and incompatible profiles remain rejected.
"""
from fractions import Fraction
import json
import math
import subprocess

FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def source_details(video, streams):
    records = [s for s in video.get('side_data_list', [])
               if 'dovi' in s.get('side_data_type', '').lower()]
    record = records[0] if len(records) == 1 else {}
    compatible = (len(records) == 1 and video.get('codec_name') == 'hevc'
        and record.get('dv_profile') == 8
        and record.get('dv_bl_signal_compatibility_id') == 1
        and record.get('bl_present_flag') == 1
        and record.get('el_present_flag') == 0
        and video.get('pix_fmt') == 'yuv420p10le'
        and video.get('color_transfer') == 'smpte2084'
        and video.get('color_primaries') == 'bt2020'
        and video.get('color_space') == 'bt2020nc')
    audio = []
    for stream in streams:
        if stream.get('codec_type') != 'audio':
            continue
        tags = stream.get('tags', {})
        audio.append({'index': stream['index'], 'language': tags.get('language', 'und'),
            'title': tags.get('title') or tags.get('name') or tags.get('handler_name', ''),
            'codec': stream.get('codec_name', ''), 'channels': stream.get('channels', 0),
            'default': bool(stream.get('disposition', {}).get('default'))})
    return {'videoStreamIndex': video.get('index'), 'dolbyVision': bool(records), 'dolbyVisionProfile': record.get('dv_profile'),
            'hdr10BaseCompatible': compatible, 'audioTracks': audio}


def source_mode(request, media):
    mode = request.get('sourceMode', 'original')
    if mode not in ('original', 'hdr10-base'):
        raise ValueError('Choose the original source or its verified HDR10-compatible base.')
    if media.get('dolbyVision'):
        if not media.get('hdr10BaseCompatible'):
            raise ValueError('This Dolby Vision profile has no verified HDR10-compatible base in this build. Choose an HDR10 or SDR source; Dolby Vision preservation is not supported.')
        if mode != 'hdr10-base':
            raise ValueError('This file has an HDR10-compatible base. Select Use HDR10 base to remove Dolby Vision metadata in a temporary copy. Dolby Vision is not preserved.')
    elif mode == 'hdr10-base':
        raise ValueError('Use HDR10 base is only available for a verified compatible Dolby Vision source.')
    return mode


def selected_audio(request, media):
    tracks = media.get('audioTracks', [])
    index = request.get('audioTrackIndex')
    if index is None:
        return tracks[0] if tracks else None
    # A JSON boolean is an int in Python, but it is never a valid stream choice.
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError('Choose an available audio track from this video.')
    selected = next((track for track in tracks if track.get('index') == index), None)
    if selected is None:
        raise ValueError('The selected audio track is not available in this video. Choose an available audio track.')
    return selected


def audio_map(request, media, remuxed=False):
    """Map absolute source indices correctly after video/audio-only remuxing."""
    selected = selected_audio(request, media)
    if selected is None:
        # Legacy metadata/test fixtures had hasAudio without a track inventory.
        return '0:a:0?' if media.get('hasAudio') else None
    if remuxed:
        ordinal = next(i for i, track in enumerate(media['audioTracks']) if track['index'] == selected['index'])
        return f'0:a:{ordinal}'
    return f"0:{selected['index']}"


def hdr10_copy_command(ffmpeg, source, destination, video_index=None):
    # Map only main video and audio. Subtitle/data/cover streams may have codecs
    # that MP4 cannot carry. The source remains the authoritative full container.
    return [ffmpeg, '-hide_banner', '-nostdin', '-n', '-copyts', '-i', str(source),
        '-map', f'0:{video_index}' if video_index is not None else '0:v:0',
        '-map', '0:a?', '-c', 'copy', '-bsf:v:0', 'dovi_rpu=strip=1',
        '-tag:v:0', 'hvc1', '-map_metadata', '0', '-map_chapters', '0',
        '-avoid_negative_ts', 'disabled', '-movflags', '+faststart',
        '-progress', 'pipe:1', '-nostats', str(destination)]


def require_dovi_filter(ffmpeg):
    result = subprocess.run([ffmpeg, '-hide_banner', '-bsfs'], capture_output=True,
        text=True, creationflags=FLAGS, timeout=15)
    if result.returncode or 'dovi_rpu' not in result.stdout.split():
        raise ValueError('This FFmpeg build cannot prepare an HDR10 base. Update the engine to a build with the dovi_rpu bitstream filter, or choose a separate HDR10 source.')


def packet_info(ffprobe, path, stream_index=None):
    result = subprocess.run([ffprobe, '-v', 'error', '-select_streams', str(stream_index) if stream_index is not None else 'v:0',
        '-count_packets', '-show_entries', 'stream=nb_read_packets,start_time,duration,avg_frame_rate',
        '-of', 'json', str(path)], capture_output=True, text=True, creationflags=FLAGS)
    if result.returncode:
        raise ValueError('Could not verify the HDR10 base packet timeline. ' + result.stderr[-1000:])
    streams = json.loads(result.stdout).get('streams', [])
    if len(streams) != 1:
        raise ValueError('The HDR10 base must contain one main video stream.')
    data = streams[0]
    count = int(data.get('nb_read_packets', 0))
    if count <= 0:
        raise ValueError('No video packets were found while verifying the HDR10 base.')
    return data


def reject_frame_dovi(ffprobe, path, stream_index=None):
    result = subprocess.run([ffprobe, '-v', 'error', '-select_streams',
        str(stream_index) if stream_index is not None else 'v:0', '-read_intervals', '%+#1',
        '-show_frames', '-of', 'json', str(path)], capture_output=True,
        text=True, creationflags=FLAGS, timeout=45)
    if result.returncode:
        raise ValueError('Could not check HDR10 base frame metadata. ' + result.stderr[-1000:])
    frames = json.loads(result.stdout).get('frames', [])
    if not frames:
        raise ValueError('No decoded frame was available to verify the HDR10 base.')
    if any('dovi' in item.get('side_data_type', '').lower() or 'dolby vision' in item.get('side_data_type', '').lower()
           for frame in frames for item in frame.get('side_data_list', [])):
        raise ValueError('The temporary copy still contains Dolby Vision frame metadata; conversion stopped.')


def verify_hdr10_copy(config, source, destination, media, copied):
    if copied.get('dolbyVision'):
        raise ValueError('The temporary copy still contains Dolby Vision signaling; conversion stopped.')
    if copied.get('codec') != 'hevc' or copied.get('pixelFormat') != 'yuv420p10le':
        raise ValueError('The temporary copy is not the expected 10-bit HEVC HDR10 base.')
    for field in ('width', 'height', 'transfer', 'primaries'):
        if copied.get(field) != media.get(field):
            raise ValueError('The HDR10 base format changed during preparation: ' + field)
    original_audio, copied_audio = media.get('audioTracks', []), copied.get('audioTracks', [])
    if len(original_audio) != len(copied_audio):
        raise ValueError('The HDR10 base copy did not retain its audio track order.')
    for original, output in zip(original_audio, copied_audio):
        if any(original.get(key) != output.get(key) for key in ('codec', 'channels', 'language')):
            raise ValueError('Audio tracks changed during HDR10 base preparation.')
    before = packet_info(config['ffprobe'], source, media.get('videoStreamIndex'))
    after = packet_info(config['ffprobe'], destination, copied.get('videoStreamIndex'))
    if int(before['nb_read_packets']) != int(after['nb_read_packets']):
        raise ValueError('HDR10 base video packet count changed.')
    for key in ('start_time', 'duration'):
        if key in before and key in after:
            left, right = float(before[key]), float(after[key])
            if not math.isfinite(left) or not math.isfinite(right) or abs(left - right) > .002:
                raise ValueError('HDR10 base video timing changed: ' + key)
    if 'avg_frame_rate' in before and 'avg_frame_rate' in after:
        left, right = Fraction(before['avg_frame_rate']), Fraction(after['avg_frame_rate'])
        if left <= 0 or right <= 0 or abs(float(left - right)) > .0001:
            raise ValueError('HDR10 base frame rate changed.')
    from hdr_trial import hdr_params
    original_hdr = hdr_params(source, config['ffprobe'], stream_index=media.get('videoStreamIndex'))
    if hdr_params(destination, config['ffprobe'], stream_index=copied.get('videoStreamIndex')) != original_hdr:
        raise ValueError('The HDR10 base did not retain its static HDR metadata.')
    reject_frame_dovi(config['ffprobe'], destination, copied.get('videoStreamIndex'))
    return {'sourceMode': 'hdr10-base', 'dolbyVisionPreserved': False,
            'dolbyVisionMetadataRemoved': True, 'videoReencoded': False,
            'videoPackets': int(after['nb_read_packets']), 'staticHDRMetadataRetained': True,
            'audioTracksRetained': len(copied_audio)}
