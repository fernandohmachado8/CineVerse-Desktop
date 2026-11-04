import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import ExitStack
from fractions import Fraction

sys.path.insert(0, str(Path(__file__).parents[1] / 'worker'))
import pipeline
import subtitles
import worker


ASS = '''[Script Info]
ScriptType: v4.00+
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:09.00,0:00:11.00,Default,,0,0,0,,Already active
Dialogue: 0,0:00:11.50,0:00:14.00,Default,,0,0,0,,{\\1c&HFFFFFF&}White override, comma\\Nsecond line
Dialogue: 0,0:00:14.00,0:00:15.00,Default,,0,0,0,,Outside
'''


def tracks():
    return [{'index': 6, 'language': 'eng', 'title': 'English dialogue', 'codec': 'mov_text',
             'default': False, 'forced': False, 'supported': True},
            {'index': 12, 'language': 'jpn', 'title': 'Japanese', 'codec': 'ass',
             'default': False, 'forced': False, 'supported': True},
            {'index': 15, 'language': 'eng', 'title': 'Bitmap', 'codec': 'hdmv_pgs_subtitle',
             'default': False, 'forced': False, 'supported': False}]


class SubtitleTests(unittest.TestCase):
    def test_probe_uses_utf8_for_unicode_language_and_track_titles(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'source.mp4'; file.write_bytes(b'video')
            result = SimpleNamespace(returncode=0, stdout=json.dumps(dict(streams=[
                dict(index=0,codec_type='video',codec_name='h264',width=960,height=540,avg_frame_rate='24/1'),
                dict(index=6,codec_type='subtitle',codec_name='mov_text',tags=dict(language='por',title='Português 日本語'))],
                format=dict(duration='2')), ensure_ascii=False))
            with patch.object(worker.subprocess,'run',return_value=result) as probe:
                media=worker.probe(dict(ffprobe='ffprobe'),file)
            self.assertEqual(media['subtitleTracks'][0]['title'],'Português 日本語')
            self.assertEqual(probe.call_args.kwargs['encoding'],'utf-8')
            self.assertEqual(probe.call_args.kwargs['errors'],'replace')

    def test_inventory_preserves_absolute_indices_languages_and_bitmap_status(self):
        streams = [{'index': 0, 'codec_type': 'video'}]
        for track in tracks():
            streams.append(dict(index=track['index'], codec_type='subtitle', codec_name=track['codec'],
                tags=dict(language=track['language'], title=track['title']), disposition=dict(default=1, forced=1)))
        inventory = subtitles.inventory(streams)
        self.assertEqual([x['index'] for x in inventory], [6, 12, 15])
        self.assertEqual(inventory[1]['language'], 'jpn')
        self.assertFalse(inventory[2]['supported'])
        self.assertTrue(inventory[0]['forced'])

    def test_off_is_explicit_default_and_ignores_unused_selection(self):
        self.assertIsNone(subtitles.selection({}, {}))
        old = pipeline.canonical_request({})
        ignored = pipeline.canonical_request(dict(subtitleMode='off', subtitleSource='external',
            subtitlePath='missing.srt', subtitleTrackIndex=999))
        self.assertEqual(old, ignored)
        self.assertEqual(old['subtitleMode'], 'off')
        self.assertIn(pipeline.IMPORT_VERSION, pipeline.SUPPORTED_VERSIONS)

    def test_burn_requires_selected_supported_text_track_and_valid_mode(self):
        media = {'subtitleTracks': tracks()}
        request = dict(subtitleMode='burn', subtitleTrackIndex=12)
        self.assertEqual(subtitles.selection(request, media)['language'], 'jpn')
        for value in (None, True, False, -1, '12', 12.0, 0, 999):
            with self.subTest(index=value), self.assertRaises(ValueError):
                subtitles.selection({**request, 'subtitleTrackIndex': value}, media)
        with self.assertRaisesRegex(ValueError, 'Bitmap'):
            subtitles.selection({**request, 'subtitleTrackIndex': 15}, media)
        for mode in ('soft', None, True):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                subtitles.selection({**request, 'subtitleMode': mode}, media)
        with self.assertRaises(ValueError):
            subtitles.selection({**request, 'subtitleSource': 'download'}, media)

    def test_external_text_file_is_bounded_utf8_and_changes_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            file = root / "caption's, semi;file.srt"
            file.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n', encoding='utf-8')
            request = dict(subtitleMode='burn', subtitleSource='external', subtitlePath=str(file))
            selected = subtitles.selection(request, {})
            first = subtitles.external_identity(selected)
            file.write_text('1\n00:00:00,000 --> 00:00:01,000\nGoodbye\n', encoding='utf-8')
            self.assertNotEqual(first, subtitles.external_identity(selected))
            self.assertEqual(selected['path'], str(file.resolve()))
            self.assertNotEqual(pipeline.canonical_request(request), pipeline.canonical_request({}))
            for bad in (root / 'missing.srt', root / 'video.mp4'):
                bad.write_text('text')
                if bad.suffix == '.srt':
                    bad.unlink()
                with self.subTest(path=bad), self.assertRaises(ValueError):
                    subtitles.selection({**request, 'subtitlePath': str(bad)}, {})
            file.write_bytes(b'\xff\xfe\x01')
            with self.assertRaisesRegex(ValueError, 'UTF-8'):
                subtitles.selection(request, {})
            file.write_bytes(b'')
            with self.assertRaisesRegex(ValueError, '20 MiB'):
                subtitles.selection(request, {})

    def test_extract_uses_original_source_absolute_stream_and_full_copyts(self):
        command = subtitles.extract_command('ffmpeg', 'original-DV.mkv', dict(source='embedded', index=12), 'private/subtitle_source.ass')
        self.assertEqual(command[command.index('-i') + 1], 'original-DV.mkv')
        self.assertEqual(command[command.index('-map') + 1], '0:12')
        self.assertIn('-copyts', command)
        self.assertNotIn('-ss', command)
        self.assertIn('-n', command)
        external = subtitles.extract_command('ffmpeg', 'movie.mkv', dict(source='external', path="D:/captions/a';b.srt"), 'private/subtitle_source.ass')
        self.assertEqual(external[external.index('-i') + 1], "D:/captions/a';b.srt")

    def test_preview_clips_straddling_cues_keeps_commas_and_normalizes_overrides(self):
        normalized, proof = subtitles.normalize_ass(ASS, 10, 3, 960, 576, 540, hdr=True)
        self.assertEqual(proof['cueCount'], 2)
        self.assertEqual(proof['cueTimes'], [{'start': 0, 'end': 1}, {'start': 1.5, 'end': 3}])
        self.assertIn('0:00:00.00,0:00:01.00', normalized)
        self.assertIn('White override, comma\\Nsecond line', normalized)
        self.assertNotIn('Outside', normalized)
        self.assertNotIn('\\1c', normalized)
        self.assertIn('&H00949494', normalized)
        self.assertFalse(proof['complexASSStylesPreserved'])

    def test_embedded_nonzero_video_start_and_external_relative_time_differ(self):
        shifted = '''[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:14.00,0:00:16.00,Default,,0,0,0,,Already active
Dialogue: 0,0:00:16.50,0:00:19.00,Default,,0,0,0,,Second cue
'''
        _, embedded = subtitles.normalize_ass(shifted, 10, 3, 960, 576, 540, video_start=5)
        self.assertEqual(embedded['windowStart'], 15)
        self.assertEqual(embedded['cueTimes'], [{'start': 0, 'end': 1}, {'start': 1.5, 'end': 3}])
        _, external = subtitles.normalize_ass(ASS, 10, 3, 960, 576, 540, video_start=5, external=True)
        self.assertEqual(external['windowStart'], 10)
        self.assertEqual(external['cueTimes'][0], {'start': 0, 'end': 1})

    def test_drawing_overrides_and_hdr_brightness_cannot_escape_plain_caption_style(self):
        self.assertEqual(subtitles.plain_text(r'{\pos(100,200)\alpha&H00&\1c&HFFFFFF&}Readable{\p1}m 0 0 l 20 20{\p0}\NText'), r'Readable\NText')
        normalized, _ = subtitles.normalize_ass(ASS, 10, 3, 1920, 1152, 1080)
        self.assertIn('&H00FFFFFF', normalized)
        self.assertNotIn('{', normalized)

    def test_no_cues_and_bad_ass_do_not_claim_a_caption(self):
        _, proof = subtitles.normalize_ass(ASS, 90, 2, 960, 576, 540)
        self.assertEqual(proof['cueCount'], 0)
        self.assertTrue(proof['noCuesInSelectedWindow'])
        with self.assertRaisesRegex(ValueError, 'ASS events'):
            subtitles.normalize_ass('not a subtitle file', 0, 2, 960, 576, 540)

    def test_burn_graph_is_fixed_local_file_two_eyes_and_explicit_main10_hdr(self):
        command = subtitles.burn_command({'ffmpeg': 'ffmpeg'}, 'stereo.mp4', 'captioned.mp4', 'cuda', True, 5)
        graph = command[command.index('-filter_complex') + 1]
        self.assertEqual(graph.count('subtitles=filename=captions.ass'), 2)
        self.assertIn('crop=iw/2:ih:0:0', graph)
        self.assertIn('crop=iw/2:ih:iw/2:0', graph)
        self.assertIn('setpts=PTS-STARTPTS', graph)
        self.assertIn('setpts=PTS+5/TB', graph)
        self.assertIn('setparams=range=limited:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc', graph)
        self.assertEqual(command[command.index('-pix_fmt') + 1], 'yuv420p10le')
        self.assertEqual(command[command.index('-profile:v') + 1], 'main10')
        self.assertEqual(command[command.index('-fps_mode') + 1], 'passthrough')
        self.assertIn('smpte2084', command)
        self.assertIn('-n', command)
        sdr = subtitles.burn_command({'ffmpeg': 'ffmpeg'}, 'stereo.mp4', 'captioned.mp4', 'cpu', False)
        self.assertEqual(sdr[sdr.index('-c:v') + 1], 'libx264')
        self.assertEqual(sdr[sdr.index('-pix_fmt') + 1], 'yuv420p')

    def test_missing_libass_fails_with_actionable_message(self):
        with patch.object(subtitles.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=' .. scale V->V\n')):
            with self.assertRaisesRegex(ValueError, 'libass'):
                subtitles.require_filter('ffmpeg')
        with patch.object(subtitles.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=' .. subtitles V->V\n')):
            subtitles.require_filter('ffmpeg')

    def test_post_burn_check_accepts_bottom_text_but_rejects_swapped_eyes(self):
        try:
            import numpy as np
            import av
        except ModuleNotFoundError:
            self.skipTest('Numeric picture verification also runs in the configured media-engine environment.')
        class Plane(np.ndarray):
            pass
        def frame(y):
            planes = []
            for array in (y, np.full((32, 64), 128, dtype=np.uint8), np.full((32, 64), 128, dtype=np.uint8)):
                plane = array.view(Plane)
                plane.height, plane.width = array.shape
                planes.append(plane)
            return SimpleNamespace(planes=planes, width=128, height=64, color_range=1, pts=0, time_base=Fraction(1,24))
        class Container:
            def __init__(self, picture):
                self.picture = picture
                self.streams = SimpleNamespace(video=[SimpleNamespace(width=128, height=64, start_time=0, time_base=Fraction(1,24), duration=48)])
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def seek(self, *args, **kwargs): pass
            def decode(self, *args): return iter([self.picture])
        original = np.full((64,128),16,dtype=np.uint8)
        original[8:56,:64] = 40
        original[8:56,64:] = 180
        captioned = original.copy()
        captioned[40:48,20:45] = 235
        captioned[40:48,84:109] = 235
        with patch.object(av, 'open', side_effect=[Container(frame(original)),Container(frame(captioned))]):
            proof = subtitles.verify_picture('before.mp4','after.mp4',False)
        self.assertEqual(len(proof['samples']),3)
        swapped = np.concatenate((captioned[:,64:],captioned[:,:64]),axis=1)
        with patch.object(av, 'open', side_effect=[Container(frame(original)),Container(frame(swapped))]):
            with self.assertRaisesRegex(ValueError,'upper picture area'):
                subtitles.verify_picture('before.mp4','after.mp4',False)

    def test_external_changed_subtitles_block_resume_before_reusing_stages(self):
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            movie = root / 'source.mp4'; movie.write_bytes(b'video')
            caption = root / 'external.srt'; caption.write_text('1\n00:00:00,000 --> 00:00:01,000\nHi\n')
            request = dict(source=str(movie), outputDir=str(root), fpsMode='original', strength=1.5, stereoMethod='forward_inpaint', subtitleMode='burn', subtitleSource='external', subtitlePath=str(caption))
            work = root / '.cineverse-jobs' / 'saved'; work.mkdir(parents=True)
            selected = subtitles.selection(request, {})
            first = subtitles.external_identity(selected)
            caption.write_text('1\n00:00:00,000 --> 00:00:01,000\nChanged\n')
            media = dict(path=str(movie), width=960, height=540, fps=24, rate='24/1', duration=2,
                hdr=False, hasAudio=False, sar='1:1', videoStart=0, subtitleTracks=[])
            state = dict(pipeline=pipeline.VERSION, request=pipeline.canonical_request(request), status='interrupted',
                completed={}, subtitleIdentity=first, sourceIdentity=pipeline.identity(movie, True))
            job = work / 'job.json'; job.write_text(json.dumps(state))
            stack.enter_context(patch.object(pipeline, 'check', return_value=dict(backend='cuda', neuralReady=True, rifeReady=False)))
            stack.enter_context(patch.object(pipeline, 'probe', return_value=media))
            stack.enter_context(patch.object(pipeline, 'emit'))
            with self.assertRaisesRegex(ValueError, 'external subtitle file changed'):
                pipeline.run({}, dict(request, resumeJob=str(job)))

    def test_pipeline_prepares_text_before_ai_but_burns_after_stereo_and_labels_no_cues(self):
        for cue_count in (0, 1):
            with self.subTest(cues=cue_count), tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
                root = Path(folder)
                movie = root / 'source.mp4'; movie.write_bytes(b'video')
                media = dict(path=str(movie), width=960, height=540, fps=24, rate='24/1', duration=2,
                    hdr=False, hasAudio=False, sar='1:1', videoStart=0, subtitleTracks=tracks())
                request = dict(source=str(movie), outputDir=str(root), fpsMode='original', preview=True,
                    previewSeconds=2, subtitleMode='burn', subtitleTrackIndex=6)
                config = dict(ffmpeg='ffmpeg', ffprobe='ffprobe', python=sys.executable,
                    cache=str(root/'cache'), iw3Repo=str(root), backend='cuda')
                commands = []
                def process(command, stage, log, *args, **kwargs):
                    commands.append(stage)
                    destination = command[command.index('--output') + 1] if '--output' in command else command[-1]
                    Path(destination).write_bytes(b'video output')
                def captions(config, original, chosen, work, *args):
                    commands.append('Preparing captions')
                    self.assertEqual(original, movie)
                    (work/'captions.ass').write_text('captions')
                    return dict(cueCount=cue_count, burnedIntoBothEyes=bool(cue_count))
                stack.enter_context(patch.object(pipeline, 'probe', return_value=media))
                stack.enter_context(patch.object(pipeline, 'check', return_value=dict(backend='cuda', gpu='Test GPU', neuralReady=True, rifeReady=False, maxWidth=1920, depthResolution=518)))
                stack.enter_context(patch.object(pipeline, 'process', side_effect=process))
                stack.enter_context(patch.object(subtitles, 'prepare', side_effect=captions))
                stack.enter_context(patch.object(subtitles, 'verify_picture', return_value=dict(samples=[])))
                stack.enter_context(patch.object(pipeline, 'timeline', side_effect=[
                    dict(width=960, height=540, frames=48, first=0, last=47/24, maxGridError=0, rate='24'),
                    dict(width=1920, height=576, frames=48, first=0, last=47/24, maxGridError=0, rate='24')]))
                stack.enter_context(patch.object(pipeline.subprocess, 'check_output', return_value=json.dumps({'streams': [dict(coded_height=576,height=576)]}).encode()))
                detail = stack.enter_context(patch.object(pipeline, 'verify_edges', return_value=dict(moviePixelsRemoved=0)))
                events = []
                stack.enter_context(patch.object(pipeline, 'emit', side_effect=lambda kind, **data: events.append((kind, data))))
                pipeline.run(config, request)
                stereo_index = commands.index('Creating stereo depth · neural gap filling')
                self.assertLess(commands.index('Preparing captions'), stereo_index)
                if cue_count:
                    self.assertGreater(commands.index('Burning subtitles into both eyes'), stereo_index)
                else:
                    self.assertNotIn('Burning subtitles into both eyes', commands)
                complete = next(data for kind, data in events if kind == 'complete')
                report = json.loads(Path(complete['report']).read_text())
                self.assertIn('_subtitles-burned' if cue_count else '_subtitles-no-cues', complete['output'])
                self.assertEqual(report['subtitles']['burnedIntoBothEyes'], bool(cue_count))
                self.assertEqual(Path(detail.call_args.args[1]).name, 'stereo.mp4')
                self.assertEqual(movie.read_bytes(), b'video')


if __name__ == '__main__':
    unittest.main()
