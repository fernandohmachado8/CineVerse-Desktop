import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parents[1]/'worker'))
import amd
import hardware as h
import pipeline
import protection as p


def rocm_torch(count=1,available=True):
    return SimpleNamespace(version=SimpleNamespace(hip='test-hip'),cuda=SimpleNamespace(
        is_available=lambda:available,device_count=lambda:count,get_device_name=lambda n:'AMD Radeon RX 7900 XTX'))


class RadeonTests(unittest.TestCase):
    def setUp(self):
        for name,value in [('IS_MAC',False),('IS_WINDOWS',True),('WINDOWS_BUILD',22631)]:
            mock=patch.object(h,name,value);mock.start();self.addCleanup(mock.stop)

    def test_hip_cuda_api_is_never_treated_as_nvidia(self):
        torch=rocm_torch()
        self.assertEqual(h.resolve({'backend':'auto'},torch),'cpu')
        with self.assertRaisesRegex(ValueError,'not NVIDIA'):h.resolve({'backend':'cuda'},torch)
        with patch.object(h,'encoder_probe',return_value=SimpleNamespace(returncode=0)) as probe:
            info=h.capabilities({'backend':'auto','ffmpeg':'ffmpeg'},torch)
        probe.assert_called_once_with('ffmpeg','cpu');self.assertNotIn('gpuUuid',info)
        self.assertIn('ROCm',info['note'])

    def test_explicit_rocm_uses_software_encoder_without_nvidia_uuid(self):
        with patch.object(h,'encoder_probe',return_value=SimpleNamespace(returncode=0)) as probe:
            info=h.capabilities({'backend':'rocm','ffmpeg':'ffmpeg'},rocm_torch())
        probe.assert_called_once_with('ffmpeg','rocm')
        self.assertEqual(info['backend'],'rocm');self.assertFalse(info['supportsHDR']);self.assertFalse(info['supports60'])
        self.assertEqual(info['gpuBinding']['name'],'AMD Radeon RX 7900 XTX')
        self.assertNotIn('gpuUuid',info);self.assertEqual(info['maxWidth'],1280)
        with patch.object(h.subprocess,'run') as run:h.encoder_probe('ffmpeg','rocm')
        self.assertIn('libx264',run.call_args.args[0]);self.assertNotIn('hevc_nvenc',run.call_args.args[0])

    def test_unsupported_runtime_os_and_multiple_devices_are_rejected(self):
        for torch in (SimpleNamespace(),rocm_torch(available=False)):
            with self.assertRaisesRegex(ValueError,'ROCm is unavailable'):h.resolve({'backend':'rocm'},torch)
        with self.assertRaisesRegex(ValueError,'exactly one'):h.resolve({'backend':'rocm'},rocm_torch(count=2))
        with patch.object(h,'WINDOWS_BUILD',19045),self.assertRaisesRegex(ValueError,'Windows 11'):h.resolve({'backend':'rocm'},rocm_torch())

    def test_rocm_plan_has_its_own_resume_identity_and_no_gpu_speed_claim(self):
        request=dict(source='synthetic.mp4',outputDir=tempfile.gettempdir(),fpsMode='original',preview=True,previewSeconds=3)
        media=dict(fps=24,rate='24',duration=3,hdr=False,sar='1:1')
        with patch.object(pipeline,'probe',return_value=media):info=pipeline.plan({'backend':'rocm'},request)
        self.assertEqual(info['backend'],'rocm');self.assertIsNone(info['estimatedSecondsLow'])
        self.assertNotEqual(pipeline.canonical_request(dict(processingBackend='rocm')),pipeline.canonical_request(dict(processingBackend='cuda')))
        with self.assertRaisesRegex(ValueError,'SDR input only'):h.validate_profile('rocm',request,dict(hdr=True))
        with self.assertRaisesRegex(ValueError,'Original FPS'):h.validate_profile('rocm',dict(fpsMode='60'),media)

    def test_cpu_and_radeon_sensors_are_both_mandatory(self):
        config=dict(backend='rocm',thermalMode='gpu')
        self.assertEqual(p.mode(config),'required')
        self.assertIn('CPU sensor unavailable',p.Monitor(config,0).sample(30,dict(gpu=dict(c=50))))
        self.assertIn('GPU',p.Monitor(config,0).sample(0,dict(cpu=dict(c=65),gpu=dict(c=90))))

    def test_linking_an_experimental_engine_does_not_reuse_stale_sensor_or_nvidia_identity(self):
        spec=importlib.util.spec_from_file_location('link_rocm',Path(__file__).parents[1]/'scripts/link_rocm_engine.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        base=dict(python='cpu-python',backend='cpu',cpuSensorFile='stale',gpuUuid='GPU-old',lastVideo='private-video',cache='existing-models')
        config=module.linked_config(base,Path('rocm-python'),Path('separate'))
        self.assertEqual(config['backend'],'rocm');self.assertEqual(config['cache'],'existing-models')
        self.assertNotIn('gpuUuid',config);self.assertNotIn('cpuSensorFile',config);self.assertNotIn('lastVideo',config)
        self.assertEqual(base['python'],'cpu-python');self.assertEqual(base['cpuSensorFile'],'stale')

    def test_linker_refuses_existing_files_before_running_a_python_engine(self):
        spec=importlib.util.spec_from_file_location('link_rocm',Path(__file__).parents[1]/'scripts/link_rocm_engine.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d,patch.object(module.subprocess,'run') as run:
            root=Path(d);base=root/'base.json';base.write_text('{}');other=root/'existing';other.mkdir();(other/'keep').write_text('preserve')
            with self.assertRaisesRegex(ValueError,'empty'):module.link(base,other)
            self.assertEqual((other/'keep').read_text(),'preserve');run.assert_not_called()


class RadeonSensorTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.file=Path(temp.name)/'cpu-sample.json'
        self.config=dict(backend='rocm',cpuSensorFile=str(self.file),gpuBinding=dict(name='AMD Radeon RX 7900 XTX',deviceCount=1,hardwareType='GpuAmd'))
        self.data=dict(timestamp=100,amdGpus=[dict(name='AMD Radeon RX 7900 XTX',id='/gpu-amd/0',hardwareType='GpuAmd',
            sensors=[dict(name='GPU Core',c=60),dict(name='GPU Hot Spot',c=95)])])

    def write(self,data=None):self.file.write_text(json.dumps(data or self.data),encoding='utf-8-sig')

    def test_unique_model_and_core_reading_bind_without_calling_nvidia_tools(self):
        self.write()
        with patch.object(p.subprocess,'run') as run,patch.object(amd.time,'time',return_value=103):
            self.assertEqual(p.gpu_reading(self.config),60);run.assert_not_called()
        self.assertEqual(amd.model_name('AMD Radeon(TM) RX 7900 XTX'),amd.model_name('Radeon RX 7900 XTX'))

    def test_stale_future_and_wrong_model_samples_fail_closed(self):
        self.write()
        for now in (99,107):
            with self.assertRaisesRegex(ValueError,'stale'):amd.gpu_reading(self.config,now)
        self.data['amdGpus'][0]['name']='AMD Radeon RX 9070 XT';self.write()
        with self.assertRaisesRegex(ValueError,'differs'):amd.gpu_reading(self.config,103)

    def test_ambiguous_or_non_radeon_adapters_are_rejected(self):
        for adapters in ([],self.data['amdGpus']*2):
            self.write(dict(self.data,amdGpus=adapters))
            with self.assertRaisesRegex(ValueError,'exactly one'):amd.gpu_reading(self.config,103)
        self.data['amdGpus'][0]['hardwareType']='GpuNvidia';self.write()
        with self.assertRaisesRegex(ValueError,'does not identify'):amd.gpu_reading(self.config,103)

    def test_hotspot_cannot_substitute_for_missing_core_and_invalid_values_fail(self):
        for value in (float('nan'),float('inf'),0,130):
            self.data['amdGpus'][0]['sensors'][0]['c']=value;self.write()
            with self.assertRaisesRegex(ValueError,'Invalid'):amd.gpu_reading(self.config,103)
        self.data['amdGpus'][0]['sensors']=self.data['amdGpus'][0]['sensors'][1:];self.write()
        with self.assertRaisesRegex(ValueError,'GPU Core'):amd.gpu_reading(self.config,103)

    def test_missing_binding_and_helper_errors_block_readings(self):
        self.write()
        with self.assertRaisesRegex(ValueError,'bind'):amd.gpu_reading(dict(self.config,gpuBinding={}),103)
        self.file.with_name('sensor-error.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'helper reported'):amd.gpu_reading(self.config,103)


if __name__=='__main__':unittest.main()
