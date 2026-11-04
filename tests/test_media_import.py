import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import ExitStack

sys.path.insert(0, str(Path(__file__).parents[1] / 'worker'))
import media_import as imp
import pipeline
import worker


def video(**changes):
    result = {'index': 2, 'codec_type': 'video', 'codec_name': 'hevc',
        'width': 1920, 'height': 1080, 'pix_fmt': 'yuv420p10le',
        'color_transfer': 'smpte2084', 'color_primaries': 'bt2020', 'color_space': 'bt2020nc',
        'avg_frame_rate': '24/1', 'sample_aspect_ratio': '1:1',
        'side_data_list': [{'side_data_type': 'DOVI configuration record', 'dv_profile': 8,
            'dv_bl_signal_compatibility_id': 1, 'bl_present_flag': 1, 'el_present_flag': 0}]}
    result.update(changes)
    return result


def streams():
    # Absolute indices intentionally have gaps and do not start with video 0.
    return [{'index': 0, 'codec_type': 'subtitle', 'codec_name': 'ass'}, video(),
        {'index': 4, 'codec_type': 'audio', 'codec_name': 'aac', 'channels': 2,
         'tags': {'language': 'eng', 'title': 'English'}, 'disposition': {'default': 1}},
        {'index': 8, 'codec_type': 'subtitle', 'codec_name': 'subrip'},
        {'index': 11, 'codec_type': 'audio', 'codec_name': 'eac3', 'channels': 6,
         'tags': {'language': 'jpn', 'name': 'Japanese'}, 'disposition': {'default': 0}}]


def media():
    return {'hdr': True, 'transfer': 'smpte2084', 'primaries': 'bt2020',
        'pixelFormat': 'yuv420p10le', 'codec': 'hevc', 'width': 1920, 'height': 1080,
        'fps': 24, 'rate': '24/1', 'duration': 100, 'bytes': 1234567, 'sar': '1:1', 'hasAudio': True,
        **imp.source_details(video(), streams())}


class MediaImportTests(unittest.TestCase):
    def test_profile_8_hdr10_compatibility_is_strict(self):
        self.assertTrue(imp.source_details(video(), streams())['hdr10BaseCompatible'])
        for field, bad in [('codec_name', 'av1'), ('pix_fmt', 'yuv420p'),
                           ('color_transfer', 'arib-std-b67'), ('color_primaries', 'bt709'),
                           ('color_space', 'ipt_c2')]:
            with self.subTest(field=field):
                self.assertFalse(imp.source_details(video(**{field: bad}), [])['hdr10BaseCompatible'])
        for field, bad in [('dv_profile', 5), ('dv_bl_signal_compatibility_id', 4),
                           ('bl_present_flag', 0), ('el_present_flag', 1)]:
            with self.subTest(field=field):
                v = video()
                v['side_data_list'][0][field] = bad
                self.assertFalse(imp.source_details(v, [])['hdr10BaseCompatible'])
        unknown = video(side_data_list=[{'side_data_type': 'DOVI configuration record'}])
        self.assertTrue(imp.source_details(unknown, [])['dolbyVision'])
        self.assertFalse(imp.source_details(unknown, [])['hdr10BaseCompatible'])
        duplicate = video()
        duplicate['side_data_list'] *= 2
        self.assertFalse(imp.source_details(duplicate, [])['hdr10BaseCompatible'])

    def test_probe_exposes_track_inventory_and_compatibility(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'example.mkv'
            source.write_bytes(b'example')
            result = SimpleNamespace(returncode=0, stdout=json.dumps({'streams': streams(), 'format': {'duration': '100'}}))
            with patch.object(worker.subprocess, 'run', return_value=result):
                value = worker.probe({'ffprobe': 'ffprobe'}, source)
        self.assertEqual(value['dolbyVisionProfile'], 8)
        self.assertEqual(value['videoStreamIndex'], 2)
        self.assertTrue(value['hdr10BaseCompatible'])
        self.assertEqual([a['index'] for a in value['audioTracks']], [4, 11])
        self.assertEqual(value['audioTracks'][1]['title'], 'Japanese')
        self.assertTrue(value['audioTracks'][0]['default'])

    def test_dolby_vision_requires_explicit_compatible_base_choice(self):
        request = {'fpsMode': 'original'}
        with self.assertRaisesRegex(ValueError, 'Select Use HDR10 base'):
            worker.validate(request, media())
        self.assertEqual(worker.validate({**request, 'sourceMode': 'hdr10-base'}, media()), (1.5, 0, 100))
        for profile in (5, 7, 9):
            bad = {**media(), 'hdr10BaseCompatible': False, 'dolbyVisionProfile': profile}
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, 'no verified HDR10-compatible base'):
                worker.validate({**request, 'sourceMode': 'hdr10-base'}, bad)
        with self.assertRaisesRegex(ValueError, 'only available'):
            worker.validate({**request, 'sourceMode': 'hdr10-base'}, {**media(), 'dolbyVision': False})
        for bad in ('tonemap', None, True):
            with self.subTest(mode=bad), self.assertRaises(ValueError):
                worker.validate({**request, 'sourceMode': bad}, media())

    def test_audio_defaults_to_first_but_explicit_selection_is_absolute(self):
        self.assertEqual(imp.selected_audio({}, media())['index'], 4)
        self.assertEqual(imp.selected_audio({'audioTrackIndex': None}, media())['index'], 4)
        self.assertEqual(imp.selected_audio({'audioTrackIndex': 11}, media())['language'], 'jpn')
        self.assertEqual(imp.audio_map({'audioTrackIndex': 11}, media()), '0:11')
        self.assertEqual(imp.audio_map({'audioTrackIndex': 11}, media(), remuxed=True), '0:a:1')
        self.assertEqual(imp.audio_map({}, media(), remuxed=True), '0:a:0')

    def test_missing_audio_and_invalid_track_selection_fail_safely(self):
        silent = {**media(), 'audioTracks': [], 'hasAudio': False}
        self.assertIsNone(imp.selected_audio({}, silent))
        self.assertIsNone(imp.audio_map({}, silent))
        for bad in (True, False, -1, '11', 11.0, 0, 2, 8, 999):
            with self.subTest(index=bad), self.assertRaisesRegex(ValueError, 'audio track'):
                imp.selected_audio({'audioTrackIndex': bad}, media())
        with self.assertRaises(ValueError):
            imp.selected_audio({'audioTrackIndex': 1}, silent)
        self.assertEqual(imp.audio_map({}, {'hasAudio': True}), '0:a:0?')

    def test_plan_includes_selected_audio_and_full_copy_space_for_preview(self):
        request = {'source': 'source.mkv', 'outputDir': tempfile.gettempdir(), 'fpsMode': 'original',
            'preview': True, 'previewSeconds': 5, 'sourceMode': 'hdr10-base', 'audioTrackIndex': 11}
        with patch.object(pipeline, 'probe', return_value=media()):
            value = pipeline.plan({}, request)
        self.assertEqual(value['sourceMode'], 'hdr10-base')
        self.assertEqual(value['selectedAudio']['index'], 11)
        self.assertEqual(value['spaceBudgetBytes'], pipeline.GIB + media()['bytes'])

    def test_resume_identity_includes_mode_and_audio_without_changing_legacy_defaults(self):
        old = pipeline.canonical_request({}, pipeline.PORTABLE_VERSION)
        self.assertEqual(old['sourceMode'], 'original')
        self.assertIsNone(old['audioTrackIndex'])
        self.assertEqual(old, pipeline.canonical_request({'sourceMode': 'original', 'audioTrackIndex': None}))
        self.assertNotEqual(old, pipeline.canonical_request({'audioTrackIndex': 11}))
        self.assertNotEqual(old, pipeline.canonical_request({'sourceMode': 'hdr10-base'}))
        self.assertIn(pipeline.PORTABLE_VERSION, pipeline.SUPPORTED_VERSIONS)
        self.assertIn(pipeline.NEURAL_VERSION, pipeline.SUPPORTED_VERSIONS)

    def test_copy_command_is_exclusive_stream_copy_not_tonemapping(self):
        command = imp.hdr10_copy_command('ffmpeg', 'original.mkv', 'private/hdr10_base.mp4')
        self.assertIn('-n', command)
        self.assertNotIn('-y', command)
        self.assertEqual(command[command.index('-c') + 1], 'copy')
        self.assertEqual(command[command.index('-bsf:v:0') + 1], 'dovi_rpu=strip=1')
        self.assertNotIn('-vf', command)
        self.assertEqual([command[i + 1] for i, arg in enumerate(command[:-1]) if arg == '-map'], ['0:v:0', '0:a?'])
        main_video = imp.hdr10_copy_command('ffmpeg', 'cover-first.mkv', 'copy.mp4', video_index=2)
        self.assertEqual(main_video[main_video.index('-map') + 1], '0:2')

    def test_unsupported_bitstream_filter_is_actionable(self):
        for result in (SimpleNamespace(returncode=0, stdout='filter_units\nhevc_metadata\n'),
                       SimpleNamespace(returncode=1, stdout='dovi_rpu\n')):
            with self.subTest(code=result.returncode), patch.object(imp.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(ValueError, 'Update the engine'):
                    imp.require_dovi_filter('ffmpeg')
        with patch.object(imp.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='dovi_rpu\n')):
            imp.require_dovi_filter('ffmpeg')

    def test_copy_verification_checks_dv_hdr_audio_packet_timeline(self):
        original = media()
        copied = {**copy.deepcopy(original), 'dolbyVision': False}
        copied['audioTracks'][0]['index'] = 1
        copied['audioTracks'][1]['index'] = 2
        packets = {'nb_read_packets': '2400', 'start_time': '0', 'duration': '100', 'avg_frame_rate': '24/1'}
        with patch.object(imp, 'packet_info', return_value=packets), patch('hdr_trial.hdr_params', return_value=['hdr10=1']), patch.object(imp, 'reject_frame_dovi'):
            proof = imp.verify_hdr10_copy({'ffprobe': 'ffprobe'}, 'source', 'copy', original, copied)
        self.assertFalse(proof['videoReencoded'])
        self.assertFalse(proof['dolbyVisionPreserved'])
        self.assertEqual(proof['videoPackets'], 2400)
        with self.assertRaisesRegex(ValueError, 'still contains Dolby Vision'):
            imp.verify_hdr10_copy({}, 'source', 'copy', original, original)
        with patch.object(imp, 'packet_info', side_effect=[packets, {**packets, 'nb_read_packets': '2399'}]):
            with self.assertRaisesRegex(ValueError, 'packet count'):
                imp.verify_hdr10_copy({'ffprobe': 'ffprobe'}, 'source', 'copy', original, copied)
        with patch.object(imp, 'packet_info', return_value=packets), patch('hdr_trial.hdr_params', side_effect=[['hdr10=1'], ['changed']]):
            with self.assertRaisesRegex(ValueError, 'static HDR metadata'):
                imp.verify_hdr10_copy({'ffprobe': 'ffprobe'}, 'source', 'copy', original, copied)

    def test_residual_frame_metadata_is_rejected_without_ignoring_static_hdr(self):
        with patch.object(imp.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps({
            'frames': [{'side_data_list': [{'side_data_type': 'Mastering display metadata'}, {'side_data_type': 'Content light level metadata'}]}]}))):
            imp.reject_frame_dovi('ffprobe', 'copy.mp4')
        for kind in ('Dolby Vision RPU Data', 'Dolby Vision Metadata', 'DOVI configuration record'):
            with self.subTest(kind=kind), patch.object(imp.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps({
                'frames': [{'side_data_list': [{'side_data_type': kind}]}]}))):
                with self.assertRaisesRegex(ValueError, 'Dolby Vision frame metadata'):
                    imp.reject_frame_dovi('ffprobe', 'copy.mp4')
        with patch.object(imp.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{"frames": []}')):
            with self.assertRaisesRegex(ValueError, 'No decoded frame'):
                imp.reject_frame_dovi('ffprobe', 'copy.mp4')

    def test_pipeline_uses_selected_audio_after_remux_and_records_original_choice(self):
        # Real orchestration/checkpoint/publication code; codecs and model worker
        # are stubbed so the test checks wiring without starting AI inference.
        with tempfile.TemporaryDirectory() as d, ExitStack() as stack:
            root = Path(d)
            source = root / 'source.mkv'
            source.write_bytes(b'original source')
            original = {**media(), 'path': str(source), 'videoStart': 0}
            copied = {**copy.deepcopy(original), 'dolbyVision': False}
            copied['audioTracks'][0]['index'] = 1
            copied['audioTracks'][1]['index'] = 2
            reference = {**copied, 'width': 100, 'height': 50, 'audioTracks': [copied['audioTracks'][1]]}
            def fake_probe(config, path):
                path = Path(path)
                if path == source:
                    return original
                if path.name == 'hdr10_base.mp4':
                    return copied
                return reference
            commands = []
            def fake_process(command, stage, log, *args, **kwargs):
                commands.append((stage, command))
                destination = command[command.index('--output') + 1] if '--output' in command else command[-1]
                Path(destination).write_bytes(b'generated video bytes')
            request = {'source': str(source), 'outputDir': str(root), 'sourceMode': 'hdr10-base',
                'audioTrackIndex': 11, 'fpsMode': 'original', 'preview': True, 'previewSeconds': 5}
            config = {'ffmpeg': 'ffmpeg', 'ffprobe': 'ffprobe', 'python': sys.executable,
                'iw3Repo': str(root), 'cache': str(root / 'cache'), 'backend': 'cuda'}
            stack.enter_context(patch.object(pipeline, 'probe', side_effect=fake_probe))
            stack.enter_context(patch.object(pipeline, 'check', return_value={'backend': 'cuda', 'gpu': 'Test GPU', 'neuralReady': True,
                'maxWidth': 1920, 'depthResolution': 518, 'rifeReady': False}))
            stack.enter_context(patch.object(pipeline, 'process', side_effect=fake_process))
            stack.enter_context(patch.object(pipeline, 'require_dovi_filter'))
            stack.enter_context(patch.object(pipeline, 'verify_hdr10_copy', return_value={'dolbyVisionPreserved': False}))
            stack.enter_context(patch('hdr_trial.hdr_params', return_value=['hdr10=1']))
            stack.enter_context(patch('hdr_sei.add_static_hdr', side_effect=lambda raw, ref, dst: Path(dst).write_bytes(Path(raw).read_bytes())))
            stack.enter_context(patch.object(pipeline, 'timeline', side_effect=[
                {'width': 100, 'height': 50, 'frames': 3, 'first': 0, 'last': 2/24, 'maxGridError': 0, 'rate': '24'},
                {'width': 200, 'height': 128, 'frames': 3, 'first': 0, 'last': 2/24, 'maxGridError': 0, 'rate': '24'}]))
            stack.enter_context(patch.object(pipeline, 'audio_hash', return_value='audiohash'))
            stack.enter_context(patch.object(pipeline.subprocess, 'check_output', return_value=json.dumps({'streams': [{'coded_height': 128, 'height': 128}]}).encode()))
            stack.enter_context(patch.object(pipeline, 'verify_edges', return_value={'moviePixelsRemoved': 0}))
            events = []
            stack.enter_context(patch.object(pipeline, 'emit', side_effect=lambda kind, **kwargs: events.append((kind, kwargs))))
            pipeline.run(config, request)
            prepare = next(command for stage, command in commands if stage == 'Preparing HDR10 video')
            maps = [prepare[i + 1] for i, arg in enumerate(prepare[:-1]) if arg == '-map']
            self.assertEqual(maps, ['0:v:0', '0:a:1'])
            self.assertIn('language=jpn', prepare)
            self.assertIn('title=Japanese', prepare)
            self.assertIn('handler_name=Japanese', prepare)
            self.assertEqual(Path(prepare[prepare.index('-i') + 1]).name, 'hdr10_base.mp4')
            complete = next(data for kind, data in events if kind == 'complete')
            report = json.loads(Path(complete['report']).read_text())
            self.assertEqual(report['selectedAudio']['index'], 11)
            self.assertEqual(report['request']['audioTrackIndex'], 11)
            self.assertFalse(report['sourceImport']['dolbyVisionPreserved'])
            self.assertEqual(source.read_bytes(), b'original source')
            self.assertFalse(any(root.glob('.cineverse-jobs/*/hdr10_base.mp4')))


if __name__ == '__main__':
    unittest.main()
