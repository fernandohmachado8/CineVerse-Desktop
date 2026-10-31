import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'worker'))
import hardware as h
import protection as p
import pipeline


def fake_torch(cuda=False):
    return SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:cuda,
        get_device_name=lambda n:'Test NVIDIA',get_device_properties=lambda n:SimpleNamespace(uuid='test')))


class CompatibilityTests(unittest.TestCase):
    def test_auto_uses_cpu_without_cuda_and_forced_cuda_fails(self):
        self.assertEqual(h.resolve({},fake_torch()),'cpu')
        self.assertEqual(h.resolve({'backend':'cpu'},SimpleNamespace()),'cpu')
        with self.assertRaisesRegex(ValueError,'unavailable'):h.resolve({'backend':'cuda'},fake_torch())
        with self.assertRaises(ValueError):h.resolve({'backend':'unknown'},fake_torch())

    def test_auto_falls_back_before_work_but_explicit_cuda_does_not(self):
        bad=SimpleNamespace(returncode=1,stderr='encoder unavailable')
        good=SimpleNamespace(returncode=0,stderr='')
        with patch.object(h,'encoder_probe',side_effect=[bad,good]) as probe:
            value=h.capabilities({'ffmpeg':'ffmpeg'},fake_torch(True))
        self.assertEqual(value['backend'],'cpu');self.assertIsNotNone(value['note'])
        self.assertEqual([c.args[1] for c in probe.call_args_list],['cuda','cpu'])
        with patch.object(h,'encoder_probe',return_value=bad):
            with self.assertRaisesRegex(ValueError,'NVENC'):h.capabilities({'backend':'cuda','ffmpeg':'ffmpeg'},fake_torch(True))

    def test_cpu_probes_only_software_encoder_and_reports_limits(self):
        with patch.object(h,'encoder_probe',return_value=SimpleNamespace(returncode=0)) as probe:
            value=h.capabilities({'backend':'cpu','ffmpeg':'ffmpeg'},SimpleNamespace())
        probe.assert_called_once_with('ffmpeg','cpu')
        self.assertFalse(value['supportsHDR']);self.assertFalse(value['supports60'])
        self.assertNotIn('gpuUuid',value);self.assertEqual(value['maxWidth'],1280)
        with patch.object(h.subprocess,'run') as run:
            h.encoder_probe('ffmpeg','cpu')
        self.assertIn('libx264',run.call_args.args[0]);self.assertNotIn('hevc_nvenc',run.call_args.args[0])

    def test_cpu_never_silently_tonemaps_or_duplicates_frames(self):
        h.validate_profile('cpu',{'fpsMode':'original'},{'hdr':False})
        with self.assertRaisesRegex(ValueError,'SDR input only'):h.validate_profile('cpu',{'fpsMode':'original'},{'hdr':True})
        with self.assertRaisesRegex(ValueError,'Original FPS'):h.validate_profile('cpu',{'fpsMode':'60'},{'hdr':False})

    def test_cpu_protection_cannot_be_disabled_by_old_gpu_only_setting(self):
        config={'backend':'cpu','thermalMode':'gpu'}
        with patch.object(p,'cpu_reading',return_value=70),patch.object(p,'gpu_reading') as gpu:
            value=p.status(config)
        self.assertTrue(value['ready']);self.assertEqual(value['mode'],'cpu')
        self.assertEqual(value['gpu']['state'],'not_used');gpu.assert_not_called()
        monitor=p.Monitor(config,0)
        self.assertIn('CPU sensor unavailable',monitor.sample(30,{'gpu':{'c':40}}))
        with patch.object(p,'cpu_reading',side_effect=ValueError('CPU missing')),patch.object(p,'gpu_reading'):
            self.assertFalse(p.status(config)['ready'])

    def test_cpu_plan_does_not_reuse_gpu_speed_estimates_and_resume_keeps_backend(self):
        import tempfile
        media={'fps':24,'rate':'24','duration':3,'hdr':False,'sar':'1:1'}
        request={'source':'synthetic.mp4','outputDir':tempfile.gettempdir(),'preview':True,'previewSeconds':3,'fpsMode':'original'}
        with patch.object(pipeline,'probe',return_value=media):
            value=pipeline.plan({'backend':'cpu'},request)
        self.assertIsNone(value['estimatedSecondsLow']);self.assertEqual(value['maxWidth'],1280)
        self.assertEqual(pipeline.canonical_request({},pipeline.NEURAL_VERSION)['processingBackend'],'cuda')
        self.assertNotEqual(pipeline.canonical_request({}),pipeline.canonical_request({'processingBackend':'cpu'}))

    @unittest.skipUnless(sys.platform=='win32','Windows venv affinity inheritance')
    def test_real_interpreter_limits_itself_before_spawning_descendants(self):
        code="""import sys,subprocess,ctypes as c
from ctypes import wintypes as w
sys.path.insert(0,sys.argv[1])
from protection import limit_cpu_process
limit_cpu_process()
check='import ctypes as c; from ctypes import wintypes as w; k=c.WinDLL("kernel32"); k.GetProcessAffinityMask.argtypes=[w.HANDLE,c.POINTER(c.c_size_t),c.POINTER(c.c_size_t)]; a,b=c.c_size_t(),c.c_size_t(); assert k.GetProcessAffinityMask(-1,c.byref(a),c.byref(b)); print(a.value.bit_count())'
print(subprocess.check_output([sys.executable,'-c',check],text=True).strip())
"""
        result=subprocess.check_output([sys.executable,'-c',code,str(Path(p.__file__).parent)],text=True)
        self.assertIn(int(result.strip()),(1,2))

    @unittest.skipUnless(sys.platform=='win32','Windows inherited CPU budget')
    def test_cpu_budget_is_applied_to_real_disposable_child(self):
        import ctypes as c
        from ctypes import wintypes as w
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],creationflags=p.FLAGS)
        try:
            p.limit_cpu_process(child)
            k=c.WinDLL('kernel32',use_last_error=True)
            k.GetProcessAffinityMask.argtypes=[w.HANDLE,c.POINTER(c.c_size_t),c.POINTER(c.c_size_t)]
            a,b=c.c_size_t(),c.c_size_t()
            self.assertTrue(k.GetProcessAffinityMask(int(child._handle),c.byref(a),c.byref(b)))
            self.assertGreater(a.value.bit_count(),0);self.assertLessEqual(a.value.bit_count(),2)
        finally:child.kill();child.wait()


if __name__=='__main__':unittest.main()
