import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'worker'))
import hardware
import macos_platform as mac
import engine_setup


class MacTests(unittest.TestCase):
    def test_mac_discovery_uses_native_paths_and_no_windows_sensor(self):
        with tempfile.TemporaryDirectory() as d,patch.object(engine_setup,'IS_MAC',True):
            root=Path(d)
            for path in ('environments/desktop-v07-macos/bin/python3','tools/ffmpeg/ffmpeg','tools/ffmpeg/ffprobe'):
                file=root/path;file.parent.mkdir(parents=True,exist_ok=True);file.touch()
            (root/'engine.json').write_text(json.dumps(dict(backend='mps')),encoding='utf8')
            data=engine_setup.discover({},[root])
            self.assertEqual(data['settings']['backend'],'mps')
            self.assertEqual(data['settings']['thermalMode'],'macos')
            self.assertTrue(Path(data['settings']['python']).is_file())
            self.assertNotIn('sensorLibrary',[c['key'] for c in data['components']])

    def test_mac_profile_rejects_hdr_and_smoothing_before_conversion(self):
        with patch.object(hardware,'IS_MAC',True):
            for backend in ('cpu','mps'):
                with self.assertRaisesRegex(ValueError,'Mac preview supports SDR'):
                    hardware.validate_profile(backend,dict(fpsMode='original'),dict(hdr=True))
                with self.assertRaisesRegex(ValueError,'not implemented on Mac'):
                    hardware.validate_profile(backend,dict(fpsMode='60'),dict(hdr=False))

    def test_auto_is_cpu_and_mps_is_explicit(self):
        torch=SimpleNamespace(backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda:True)))
        with patch.object(hardware,'IS_MAC',True):
            self.assertEqual(hardware.resolve({'backend':'auto'},torch),'cpu')
            self.assertEqual(hardware.resolve({'backend':'mps'},torch),'mps')
            with self.assertRaisesRegex(ValueError,'NVIDIA'):hardware.resolve({'backend':'cuda'},torch)
            self.assertEqual(hardware.capabilities({'backend':'mps'},torch,probe=False)['maxWidth'],1280)

    def test_unavailable_mps_fails_without_pretending_to_accelerate(self):
        with patch.object(hardware,'IS_MAC',True),self.assertRaisesRegex(ValueError,'unavailable'):
            hardware.resolve({'backend':'mps'},SimpleNamespace())

    def test_thermal_state_is_not_a_celsius_sample(self):
        with patch.object(mac.subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps({'thermalState':1}))) as run:
            data=mac.status({})
        self.assertTrue(data['ready']);self.assertEqual(data['cpu']['label'],'Fair');self.assertNotIn('c',data['cpu'])
        self.assertEqual(run.call_args.args[0][0],'/usr/bin/osascript')

    def test_critical_serious_and_sensor_loss(self):
        m=mac.Monitor(0)
        state=lambda n:{'cpu':{'thermalState':n}}
        self.assertIsNone(m.sample(0,state(2)))
        self.assertIsNone(m.sample(9.9,state(2)))
        self.assertIn('Serious',m.sample(10,state(2)))
        self.assertIsNone(m.sample(11,state(1)))
        self.assertIn('Critical',m.sample(12,state(3)))
        self.assertIn('30 seconds',m.sample(42,{}))

    def test_missing_or_invalid_reading_blocks_arming(self):
        for value in ('2',True,5,None):
            with patch.object(mac.subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps({'thermalState':value}))):
                self.assertFalse(mac.status({})['ready'])
        with patch.object(mac.subprocess,'run',side_effect=subprocess.TimeoutExpired('osascript',3)):
            self.assertFalse(mac.status({})['ready'])

    def test_runtime_and_video_tool_downloads_are_pinned(self):
        m=json.loads((Path(__file__).parents[1]/'requirements/engine-manifest.json').read_text(encoding='utf8'))['macosArm64']
        for asset in [m['bootstrapPython'],*m['ffmpegAssets']]:
            self.assertRegex(asset['sha256'],'^[a-f0-9]{64}$');self.assertTrue(asset['url'].startswith('https://'))


if __name__=='__main__':unittest.main()
