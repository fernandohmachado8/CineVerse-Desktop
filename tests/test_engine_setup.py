import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).parents[1] / 'worker'))
from engine_setup import discover


class SetupTests(unittest.TestCase):
    def test_manifest_fills_missing_but_preserves_valid_custom_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); original = root/'python-custom.exe'; original.touch()
            installed = root/'python.exe'; installed.touch()
            probe = root/'ffprobe.exe'; probe.touch()
            (root/'engine.json').write_text(json.dumps({'python':str(installed),'ffprobe':str(probe)}))
            result = discover({'python':str(original),'ffprobe':'gone','lastVideo':'keep.mkv','outputDir':'chosen'}, [root])
            self.assertEqual(result['settings']['python'], str(original))
            self.assertEqual(result['settings']['ffprobe'], str(probe))
            self.assertEqual(result['settings']['lastVideo'], 'keep.mkv')
            self.assertEqual(result['settings']['outputDir'], 'chosen')
            self.assertEqual(result['settings']['thermalMode'], 'required')

    def test_bounded_layout_detection_and_partial_status(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); lib = root/'tools/thermal-guard/LibreHardwareMonitor'; lib.mkdir(parents=True)
            (lib/'LibreHardwareMonitorLib.dll').touch()
            result = discover({}, [root])
            self.assertEqual(result['settings']['sensorLibrary'], str(lib))
            found = {c['key']:c['found'] for c in result['components']}
            self.assertTrue(found['sensorLibrary']); self.assertFalse(found['rifeModel'])

    def test_bad_manifest_does_not_break_detection(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'engine.json').write_text('invalid json')
            self.assertEqual(discover({'thermalMode':'gpu'}, [d])['settings']['thermalMode'], 'gpu')


if __name__ == '__main__': unittest.main()
