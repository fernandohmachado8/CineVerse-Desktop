import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'worker'))
import protection as p


def reading(cpu=65, gpu=55):
    return dict(ready=True, mode='required', cpu=dict(state='ready', c=cpu), gpu=dict(state='ready', c=gpu))


class ProtectionTests(unittest.TestCase):
    def test_powershell_resource_paths_keep_normal_local_semantics(self):
        self.assertEqual(p.shell_path('\\\\?\\D:\\engine\\cpu.ps1'), 'D:\\engine\\cpu.ps1')
        self.assertEqual(p.shell_path('\\\\?\\UNC\\server\\share\\cpu.ps1'), '\\\\server\\share\\cpu.ps1')

    def test_immediate_cutoffs(self):
        for cpu, gpu, name in [(100, 60, 'CPU'), (70, 90, 'GPU')]:
            self.assertIn(name, p.Monitor({}, 0).sample(0, reading(cpu, gpu)))

    def test_already_hot_sensor_blocks_arming(self):
        with patch.object(p, 'cpu_reading', return_value=100), patch.object(p, 'gpu_reading', return_value=55):
            self.assertFalse(p.status({})['ready'])
            self.assertEqual(p.status({})['cpu']['state'], 'too_hot')
            self.assertTrue(p.status({'thermalMode': 'gpu'})['ready'])

    def test_sustained_threshold_and_reset(self):
        m = p.Monitor({}, 0)
        self.assertIsNone(m.sample(0, reading(95)))
        self.assertIsNone(m.sample(9.99, reading(95)))
        self.assertIn('10 seconds', m.sample(10, reading(95)))
        m.sample(11, reading(94)); self.assertIsNone(m.sample(12, reading(95)))
        self.assertIsNone(m.sample(21, reading(95)))
        self.assertIn('CPU', m.sample(22, reading(95)))

    def test_required_sensor_loss_fails_closed(self):
        m = p.Monitor({}, 0); data = reading(); data['cpu'] = {'state': 'unavailable'}
        self.assertIsNone(m.sample(29.9, data))
        self.assertIn('CPU sensor unavailable', m.sample(30, data))

    def test_gpu_only_does_not_claim_or_require_cpu_protection(self):
        m = p.Monitor({'thermalMode': 'gpu'}, 0)
        self.assertIsNone(m.sample(300, {'gpu': {'c': 50}}))
        self.assertIn('GPU sensor unavailable', m.sample(330, {}))
        with self.assertRaises(ValueError): p.mode({'thermalMode': 'off'})

    def test_sensor_recovery_resets_missing_clock(self):
        m = p.Monitor({}, 0)
        m.sample(29, reading())
        self.assertIsNone(m.sample(50, {}))
        self.assertIn('CPU', m.sample(59, {}))

    def test_cpu_freshness_filter_invalid_and_bom(self):
        with tempfile.TemporaryDirectory() as d:
            file = Path(d) / 'cpu-sample.json'; cfg = {'cpuSensorFile': str(file)}
            data = {'timestamp': 100, 'sensors': [{'name': 'CPU Package', 'c': 70}, {'name': 'Distance to TjMax', 'c': 99}]}
            file.write_text(json.dumps(data), encoding='utf-8-sig')
            self.assertEqual(p.cpu_reading(cfg, 103), 70)
            for now in (99, 107):
                with self.assertRaisesRegex(ValueError, 'stale'): p.cpu_reading(cfg, now)
            data['sensors'][0]['c'] = float('nan'); file.write_text(json.dumps(data))
            with self.assertRaises(ValueError): p.cpu_reading(cfg, 101)

    def test_gpu_uuid_is_bound_and_read_timeout_is_bounded(self):
        with patch.object(p.subprocess, 'run', return_value=SimpleNamespace(stdout='GPU-right, 60')) as run:
            self.assertEqual(p.gpu_reading({'gpuUuid': 'GPU-right'}), 60)
            self.assertEqual(run.call_args.kwargs['timeout'], 2)
            with self.assertRaisesRegex(ValueError, 'different GPU'): p.gpu_reading({'gpuUuid': 'GPU-wrong'})

    def test_missing_cpu_blocks_before_converter_spawn(self):
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, get_device_name=lambda n: "Test GPU", get_device_properties=lambda n: SimpleNamespace(uuid='test')))
        with patch.dict(sys.modules, torch=torch), patch.object(p, 'status', return_value=dict(reading(), ready=False, cpu={'state':'unavailable','message':'CPU missing'})), patch.object(p.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ValueError, 'not started'): p.supervise({}, {}, lambda *a, **k: None)
            spawn.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows process-tree integration')
    def test_hot_reading_stops_real_dummy_tree_and_keeps_unrelated_process(self):
        real_popen = subprocess.Popen
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, get_device_name=lambda n: "Test GPU", get_device_properties=lambda n: SimpleNamespace(uuid='test')))
        processes = []
        with tempfile.TemporaryDirectory() as d:
            # The actual child spawns a descendant; only this tree may be stopped.
            code = "import subprocess,sys,json,time; json.load(sys.stdin); c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(90)']); print(json.dumps({'type':'started','workDir':sys.argv[1],'descendant':c.pid}),flush=True); time.sleep(90)"
            unrelated = real_popen([sys.executable, '-c', 'import time;time.sleep(90)'], creationflags=p.FLAGS)
            def launch(command, *args, **kwargs):
                if command[-1] != 'convert': return real_popen(command, *args, **kwargs)
                child = real_popen([sys.executable, '-u', '-c', code, d], **kwargs); processes.append(child); return child
            events = []
            def emit(kind, **data): events.append(dict(type=kind, **data))
            try:
                with patch.dict(sys.modules, torch=torch), patch.object(p.subprocess, 'Popen', side_effect=launch), patch.object(p, 'status', side_effect=[reading(), reading(100)]):
                    with self.assertRaisesRegex(RuntimeError, 'Thermal protection stopped'): p.supervise({}, {}, emit)
                self.assertIsNotNone(processes[0].poll())
                self.assertIsNone(unrelated.poll())
                descendant = next(e['descendant'] for e in events if 'descendant' in e)
                self.assertIsNone(p.identity(descendant))
                self.assertTrue((Path(d) / 'thermal-stop.json').is_file())
                self.assertIn('stopping', [e.get('state') for e in events])
            finally:
                unrelated.kill(); unrelated.wait()

    @unittest.skipUnless(os.name == 'nt', 'Windows kernel job cleanup')
    def test_job_object_closing_terminates_child(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(90)'], creationflags=p.FLAGS)
        try:
            job = p.ProcessTree(child); job.close()
            child.wait(timeout=5)
            self.assertIsNotNone(child.poll())
        finally:
            if child.poll() is None: child.kill(); child.wait()

    @unittest.skipUnless(os.name == 'nt', 'Windows process-tree cleanup')
    def test_supervisor_failure_does_not_leave_dummy_converter_running(self):
        real_popen = subprocess.Popen
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, get_device_name=lambda n: "Test GPU", get_device_properties=lambda n: SimpleNamespace(uuid='test')))
        processes = []
        def launch(command, *args, **kwargs):
            if command[-1] != 'convert': return real_popen(command, *args, **kwargs)
            child = real_popen([sys.executable, '-u', '-c', 'import sys,json,time;json.load(sys.stdin);time.sleep(90)'], **kwargs)
            processes.append(child); return child
        with patch.dict(sys.modules, torch=torch), patch.object(p.subprocess, 'Popen', side_effect=launch), patch.object(p, 'status', side_effect=[reading(), RuntimeError('monitor failed')]):
            with self.assertRaisesRegex(RuntimeError, 'monitor failed'): p.supervise({}, {}, lambda *a, **k: None)
        self.assertIsNotNone(processes[0].poll())


if __name__ == '__main__': unittest.main()
