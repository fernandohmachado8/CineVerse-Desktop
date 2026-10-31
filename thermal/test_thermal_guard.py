import unittest
from thermal_guard import Policy, identity, stop_tree, sensor_lost
import os
import subprocess
import sys
import tempfile
import json
import time
from pathlib import Path
from unittest.mock import patch
from thermal_guard import run


class ThermalTests(unittest.TestCase):
    def test_brief_peak_does_not_stop(self):
        p = Policy()
        for t,c in [(0,80),(2,90),(4,95),(6,80),(20,80)]:
            self.assertIsNone(p.sample(c,t))

    def test_sustained_threshold(self):
        p=Policy()
        self.assertIsNone(p.sample(95,0))
        self.assertIsNone(p.sample(96,9))
        self.assertIn('10 seconds',p.sample(95,10))

    def test_resets_on_cooling(self):
        p=Policy()
        for t,c in [(0,96),(8,94),(10,96),(18,96)]:
            self.assertIsNone(p.sample(c,t))
        self.assertIsNotNone(p.sample(96,20))

    def test_emergency(self):
        self.assertIsNotNone(Policy().sample(100,0))

    def test_invalid_sensor(self):
        for c in [0,float('nan'),float('inf'),200]:
            with self.assertRaises(ValueError): Policy().sample(c,0)

    def test_sensor_failure_requires_armed_guard_and_30_seconds(self):
        self.assertFalse(sensor_lost(False,300,0))
        self.assertFalse(sensor_lost(True,29,0))
        self.assertTrue(sensor_lost(True,30,0))

    def test_identity_bound_and_stop_dummy_only(self):
        dummy=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])
        try:
            target=identity(dummy.pid)
            wrong=dict(target,created=target['created']+1)
            with self.assertRaises(RuntimeError): stop_tree(wrong)
            self.assertIsNone(dummy.poll())
            stop_tree(target)
            dummy.wait(timeout=5)
            self.assertIsNone(identity(dummy.pid))
            self.assertEqual(identity(os.getpid())['pid'],os.getpid())
        finally:
            if dummy.poll() is None: dummy.kill()

    def test_full_watchdog_stops_dummy_from_bom_sensor_file(self):
        dummy=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])
        try:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                (root/'guard-config.json').write_text(json.dumps({'target':identity(dummy.pid)}),encoding='utf-8-sig')
                (root/'cpu-sample.json').write_text(json.dumps({'timestamp':time.time(),'sensors':[{'name':'CPU Package','c':100},{'name':'Distance to TjMax','c':0}]}),encoding='utf-8-sig')
                with patch('thermal_guard.alert'):
                    run(root/'guard-config.json')
                dummy.wait(timeout=5)
                self.assertEqual(json.loads((root/'status.json').read_text())['state'],'stopped')
                self.assertTrue((root/'sensor-stop.flag').exists())
        finally:
            if dummy.poll() is None: dummy.kill()


if __name__=='__main__': unittest.main()
