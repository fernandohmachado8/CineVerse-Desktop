"""Text subtitle selection, bounded cue timing and matching SBS burn-in.

Captions are rendered after stereo reconstruction, at zero disparity in both
eyes. ASS layout/effects are deliberately normalized to a plain caption style.
"""
import hashlib
import math
from pathlib import Path
import re
import subprocess

FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
TEXT_CODECS = {'subrip', 'srt', 'ass', 'ssa', 'mov_text', 'webvtt', 'text'}
MAX_TEXT_BYTES = 20 * 1024 ** 2


def inventory(streams):
    result = []
    for stream in streams:
        if stream.get('codec_type') != 'subtitle':
            continue
        tags, disposition = stream.get('tags', {}), stream.get('disposition', {})
        codec = stream.get('codec_name', '')
        result.append({'index': stream['index'], 'language': tags.get('language', 'und'),
            'title': tags.get('title') or tags.get('name') or tags.get('handler_name', ''),
            'codec': codec, 'default': bool(disposition.get('default')),
            'forced': bool(disposition.get('forced')), 'supported': codec in TEXT_CODECS})
    return result


def canonical(request):
    mode = request.get('subtitleMode', 'off')
    if mode not in ('off', 'burn'):
        raise ValueError('Choose subtitles off or Burn subtitles into both eyes.')
    if mode == 'off':
        return {'subtitleMode': 'off', 'subtitleSource': 'embedded',
                'subtitleTrackIndex': None, 'subtitlePath': None}
    source = request.get('subtitleSource', 'embedded')
    if source not in ('embedded', 'external'):
        raise ValueError('Choose an embedded subtitle track or an external SRT/ASS file.')
    return {'subtitleMode': mode, 'subtitleSource': source,
        'subtitleTrackIndex': request.get('subtitleTrackIndex') if source == 'embedded' else None,
        'subtitlePath': request.get('subtitlePath') if source == 'external' else None}


def selection(request, media):
    choices = canonical(request)
    if choices['subtitleMode'] == 'off':
        return None
    if choices['subtitleSource'] == 'embedded':
        index = choices['subtitleTrackIndex']
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError('Choose a subtitle language/track before enabling burn-in.')
        track = next((track for track in media.get('subtitleTracks', []) if track['index'] == index), None)
        if not track:
            raise ValueError('The selected subtitle track is not available in this video.')
        if not track.get('supported') or track.get('codec') not in TEXT_CODECS:
            raise ValueError('Bitmap/unknown subtitle tracks are not supported. Choose a text track or an external SRT/ASS file; OCR is not implemented.')
        return dict(track, source='embedded')
    value = choices['subtitlePath']
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Choose an external SRT or ASS subtitle file.')
    path = Path(value).resolve()
    if path.suffix.lower() not in ('.srt', '.ass') or not path.is_file():
        raise ValueError('External subtitles must be an existing SRT or ASS file.')
    if not 0 < path.stat().st_size <= MAX_TEXT_BYTES:
        raise ValueError('External subtitle text must contain between 1 byte and 20 MiB.')
    try:
        path.read_text(encoding='utf-8-sig')
    except (UnicodeDecodeError, OSError) as exc:
        raise ValueError('External subtitles must be readable UTF-8 SRT/ASS text. Save the file as UTF-8 and try again.') from exc
    return {'index': None, 'language': 'und', 'title': path.name, 'codec': path.suffix[1:].lower(),
        'default': False, 'forced': False, 'supported': True, 'source': 'external', 'path': str(path)}


def external_identity(selected):
    if not selected or selected['source'] != 'external':
        return None
    path = Path(selected['path'])
    stat = path.stat()
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': stat.st_size, 'mtimeNS': stat.st_mtime_ns, 'sha256': digest}


def require_filter(ffmpeg):
    result = subprocess.run([ffmpeg, '-hide_banner', '-filters'], capture_output=True,
        text=True, creationflags=FLAGS, timeout=15)
    if result.returncode or not any(len(line.split()) >= 2 and line.split()[1] == 'subtitles'
                                   for line in result.stdout.splitlines()):
        raise ValueError('This FFmpeg build lacks the libass subtitles filter. Update the engine to enable subtitle burn-in.')


def extract_command(ffmpeg, original, selected, destination):
    source = selected['path'] if selected['source'] == 'external' else str(original)
    stream = '0:s:0' if selected['source'] == 'external' else f"0:{selected['index']}"
    # Full text extraction retains cues already active when a preview begins.
    return [ffmpeg, '-hide_banner', '-nostdin', '-n', '-copyts', '-i', source,
        '-map', stream, '-c:s', 'ass', '-vn', '-an', '-avoid_negative_ts', 'disabled',
        '-f', 'ass', str(destination)]


def _seconds(value):
    parts = value.strip().split(':')
    if len(parts) != 3:
        raise ValueError('Invalid ASS cue timestamp.')
    hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
    result = hours * 3600 + minutes * 60 + seconds
    if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60 or not math.isfinite(result):
        raise ValueError('Invalid ASS cue timestamp.')
    return result


def _timestamp(value):
    centiseconds = max(0, round(value * 100))
    hours, rest = divmod(centiseconds, 360000)
    minutes, rest = divmod(rest, 6000)
    seconds, fraction = divmod(rest, 100)
    return f'{hours}:{minutes:02}:{seconds:02}.{fraction:02}'


def plain_text(value):
    # No arbitrary position, karaoke, alpha, color or font directives can
    # override the shared caption plane or HDR white level. Ignore drawings.
    chunks, drawing = [], False
    for part in re.split(r'(\{[^}]*\})', value):
        if part.startswith('{') and part.endswith('}'):
            commands = re.findall(r'\\p(\d+)', part)
            if commands:
                drawing = commands[-1] != '0'
        elif not drawing:
            chunks.append(part)
    return ''.join(chunks).replace(r'\n', r'\N').strip()


def normalize_ass(text, start, seconds, width, height, content_height, hdr=False, video_start=0, external=False):
    if not math.isfinite(start) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Invalid subtitle preview interval.')
    window = start + (0 if external else video_start)
    event_fields, in_events, cues = None, False, []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('['):
            in_events = stripped.lower() == '[events]'
        elif in_events and stripped.lower().startswith('format:'):
            event_fields = [field.strip().lower() for field in stripped.split(':', 1)[1].split(',')]
        elif in_events and stripped.lower().startswith('dialogue:'):
            if not event_fields or any(name not in event_fields for name in ('start', 'end', 'text')):
                raise ValueError('ASS subtitles do not contain a supported event format.')
            values = stripped.split(':', 1)[1].lstrip().split(',', len(event_fields) - 1)
            if len(values) != len(event_fields):
                raise ValueError('Malformed subtitle event.')
            data = dict(zip(event_fields, values))
            begin, end = _seconds(data['start']), _seconds(data['end'])
            caption = plain_text(data['text'])
            if not caption or end <= window or begin >= window + seconds or end <= begin:
                continue
            clipped_start, clipped_end = max(0, begin - window), min(seconds, end - window)
            if round(clipped_end * 100) > round(clipped_start * 100):
                cues.append((clipped_start, clipped_end, caption))
    if not in_events and event_fields is None:
        raise ValueError('Subtitle extraction did not produce ASS events.')
    white = '&H00949494' if hdr else '&H00FFFFFF'
    font_size = max(14, round(content_height * .036))
    margin = max(20, round(width * .035))
    bottom = height - content_height - ((height - content_height) // 4) * 2
    margin_v = bottom + max(16, round(content_height * .045))
    outline = max(1, round(content_height / 540 * 2))
    lines = ['[Script Info]', 'ScriptType: v4.00+', f'PlayResX: {width}', f'PlayResY: {height}',
        'WrapStyle: 0', 'ScaledBorderAndShadow: yes', '', '[V4+ Styles]',
        'Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding',
        f'Style: Default,Arial,{font_size},{white},{white},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{outline},0,2,{margin},{margin},{margin_v},1',
        '', '[Events]', 'Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text']
    lines += [f'Dialogue: 0,{_timestamp(begin)},{_timestamp(end)},Default,,0,0,0,,{caption}' for begin, end, caption in cues]
    report = {'cueCount': len(cues), 'cueTimes': [{'start': a, 'end': b} for a, b, _ in cues],
        'windowStart': window, 'windowSeconds': seconds, 'style': 'normalized plain bottom-centred text',
        'complexASSStylesPreserved': False, 'zeroDisparity': True,
        'HDRCaptionWhiteApproxNits': 200 if hdr else None,
        'noCuesInSelectedWindow': not cues}
    return '\n'.join(lines) + '\n', report


def prepare(config, original, selected, work, start, seconds, media, reference, process):
    require_filter(config['ffmpeg'])
    extracted = work / 'subtitle_source.ass'
    process(extract_command(config['ffmpeg'], original, selected, extracted), 'Extracting selected subtitles', work / 'conversion.log')
    if extracted.stat().st_size > MAX_TEXT_BYTES:
        raise ValueError('Extracted subtitle text exceeds the 20 MiB limit.')
    text = extracted.read_text(encoding='utf-8-sig')
    height = ((reference['height'] + 16 + 63) // 64) * 64
    normalized, proof = normalize_ass(text, start, seconds, reference['width'], height, reference['height'],
        hdr=media['hdr'], video_start=media.get('videoStart', 0), external=selected['source'] == 'external')
    (work / 'captions.ass').write_text(normalized, encoding='utf-8')
    return dict(proof, selectedSubtitle=selected, mode='burn', burnedIntoBothEyes=bool(proof['cueCount']),
        subtitleFormat='text', embeddedSubtitleStreamsRetained=False)


def burn_command(config, raw, destination, backend, hdr, first_timestamp=0):
    if not math.isfinite(first_timestamp):
        raise ValueError('Invalid caption video timestamp.')
    pixel_format = 'yuv420p10le' if hdr else 'yuv420p'
    params = ',setparams=range=limited:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc' if hdr else ''
    graph = (f'[0:v:0]setpts=PTS-STARTPTS,format={pixel_format},split=2[sl][sr];'
        f'[sl]crop=iw/2:ih:0:0,format={pixel_format},subtitles=filename=captions.ass[cl];'
        f'[sr]crop=iw/2:ih:iw/2:0,format={pixel_format},subtitles=filename=captions.ass[cr];'
        f'[cl][cr]hstack=inputs=2,format={pixel_format}{params},setpts=PTS+{first_timestamp}/TB[v]')
    codec = 'libx264' if backend in ('cpu', 'mps', 'rocm') else 'hevc_nvenc' if hdr else 'h264_nvenc'
    encoding = ['-preset', 'medium', '-crf', '18', '-threads', '2'] if codec == 'libx264' else ['-preset', 'p6', '-rc', 'constqp', '-qp', '12']
    colors = ['-color_primaries', 'bt2020', '-color_trc', 'smpte2084', '-colorspace', 'bt2020nc', '-color_range', 'tv'] if hdr else []
    return [config['ffmpeg'], '-hide_banner', '-nostdin', '-n', '-copyts', '-i', str(raw),
        '-filter_complex_threads', '2', '-filter_complex', graph, '-map', '[v]', '-an',
        '-c:v', codec, *encoding, '-pix_fmt', pixel_format, '-fps_mode', 'passthrough',
        '-enc_time_base:v', '1:90000', '-video_track_timescale', '90000',
        *(['-profile:v', 'main10', '-tag:v', 'hvc1'] if hdr else []), *colors,
        '-avoid_negative_ts', 'disabled', '-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', str(destination)]


def verify_picture(raw, final, hdr):
    """Check both eyes outside the intended bottom caption area and margins.

    This is a sampled codec/picture-integrity check, not proof of readability,
    full-movie geometry, perceptual quality or comfort in a headset.
    """
    import av
    import numpy as np
    samples = []
    maximum = 1023 if hdr else 255
    with av.open(str(raw)) as before, av.open(str(final)) as after:
        left_stream, right_stream = before.streams.video[0], after.streams.video[0]
        if (left_stream.width, left_stream.height) != (right_stream.width, right_stream.height):
            raise ValueError('Subtitle burn-in changed the stereo picture dimensions.')
        def at(container, relative):
            stream = container.streams.video[0]
            first = (stream.start_time or 0) * stream.time_base
            target = float(first) + relative
            container.seek(int(target / float(stream.time_base)), stream=stream, backward=True)
            last = None
            for frame in container.decode(stream):
                last = frame
                if float(frame.pts * frame.time_base) >= target - .0001:
                    return frame
            return last
        duration = float(left_stream.duration * left_stream.time_base) if left_stream.duration else float(before.duration / av.time_base)
        for relative in (0, .25, 1, 5, 30, 60, 120):
            if relative >= duration:
                continue
            a, b = at(before, relative), at(after, relative)
            if a is None or b is None:
                raise ValueError('Could not decode the subtitle picture-verification sample.')
            dtype = np.uint16 if hdr else np.uint8
            def plane(frame, index):
                p = frame.planes[index]
                return np.frombuffer(p, dtype=dtype).reshape(p.height, -1)[:, :p.width].astype(float)
            source, output = plane(a, 0), plane(b, 0)
            eye_width = a.width // 2
            upper = max(1, int(a.height * .4))
            errors = []
            for eye in (0, 1):
                region = slice(eye * eye_width, (eye + 1) * eye_width)
                error = float(np.abs(source[:upper, region] - output[:upper, region]).mean()) / maximum
                if error > .02:
                    raise ValueError('Subtitle burn-in changed the upper picture area. Shorten long captions or choose a different subtitle track; no export was published.')
                errors.append(error)
            black = 0 if b.color_range == 2 else 64 if hdr else 16
            neutral = 512 if hdr else 128
            guards = []
            for index in range(3):
                values = plane(b, index)
                rows, expected = (4, neutral) if index else (8, black)
                error = float(np.abs(np.concatenate((values[:rows], values[-rows:])) - expected).mean()) / maximum
                if error > .01:
                    raise ValueError('Subtitle burn-in changed the black compatibility margins.')
                guards.append(error)
            samples.append({'relativeTime': relative, 'upperPictureMAENormalizedPerEye': errors,
                            'guardMAENormalizedYUV': guards})
    return {'scope': 'sampled upper 40 percent of both eyes and black margins after burn-in',
            'samples': samples, 'perceptualReadabilityVerified': False}
