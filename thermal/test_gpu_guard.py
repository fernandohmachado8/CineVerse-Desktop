import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from thermal_guard import Policy,identity
from gpu_guard import parse_gpu,run


class GpuTests(unittest.TestCase):
    def test_gpu_sustained_threshold_and_reset(self):
        policy=Policy('GPU',85,90)
        for t,c in [(0,85),(8,84),(10,85),(18,89)]:
            self.assertIsNone(policy.sample(c,t))
        self.assertIn('GPU stayed',policy.sample(85,20))

    def test_gpu_immediate_threshold(self):
        self.assertIn('GPU reached 90',Policy('GPU',85,90).sample(90,0))

    def test_cpu_threshold_unchanged(self):
        self.assertIsNone(Policy().sample(90,0))

    def test_uuid_bound_and_invalid_readings(self):
        self.assertEqual(parse_gpu('GPU-test, 52.5\n','GPU-test'),52.5)
        for value in ['GPU-other, 52','GPU-test, N/A','GPU-test, nan','GPU-test, 500','GPU-test, 52\nGPU-other, 53']:
            with self.assertRaises(ValueError): parse_gpu(value,'GPU-test')

    def test_actual_stop_dummy_on_simulated_gpu_heat(self):
        self.exercise([90])

    def test_actual_stop_dummy_on_sensor_loss_after_arming(self):
        self.exercise([52,ValueError('GPU sensor disconnected')],lost=True)

    def exercise(self,readings,lost=False):
        dummy=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])
        try:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);config=root/'gpu-config.json'
                config.write_text(json.dumps({'target':identity(dummy.pid),'gpuUuid':'GPU-test'}))
                with patch('gpu_guard.read_gpu',side_effect=readings),patch('gpu_guard.alert'),patch('gpu_guard.time.sleep'),patch('gpu_guard.time.monotonic',side_effect=[0,0,31] if lost else [0,0]):
                    run(config)
                dummy.wait(timeout=5)
                state=json.loads((root/'gpu-status.json').read_text())
                self.assertEqual(state['state'],'stopped')
                self.assertIn('sensor unavailable' if lost else 'GPU reached 90',state['reason'])
        finally:
            if dummy.poll() is None: dummy.kill()


if __name__=='__main__': unittest.main()
