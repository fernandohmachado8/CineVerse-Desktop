"""Simulated inventory is selection coverage, never Radeon hardware validation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
import tempfile
import zipfile
from unittest.mock import Mock, patch

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import hardware_detect as detect
spec=importlib.util.spec_from_file_location('automatic_setup',ROOT/'scripts/setup_engine.py')
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
sys.path.insert(0,str(ROOT/'worker'))
import hardware


def inventory(name='AMD Radeon RX 7900 XTX',driver='32.0.23027.2005'):
    return dict(state='detected',architecture='x64',desktop=True,windowsBuild=22631,
        gpus=[dict(name=name,driverVersion=driver,vendorId='1002',healthy=True)])


class AutomaticHardwareTests(unittest.TestCase):
    def setUp(self):
        self.manifest=json.loads(setup.MANIFEST.read_text(encoding='utf8'))
        self.recipe=self.manifest['rocmProfile']

    def test_each_explicitly_supported_model_can_attempt_the_pinned_recipe(self):
        for model in self.recipe['supportedModels']:
            with self.subTest(model=model):
                decision=detect.choose(inventory(model['name']),self.recipe)
                self.assertEqual(decision['backend'],'rocm')
                self.assertEqual(decision['architecture'],model['architecture'])
        self.assertEqual(detect.choose(inventory('AMD Radeon(TM) RX 7900 XTX'),self.recipe)['backend'],'rocm')

    def test_unlisted_models_are_not_inferred_from_the_brand_or_similar_names(self):
        for name in ('AMD Radeon RX 7700 XT','AMD Radeon RX 7900 XT','AMD Radeon Graphics','Intel Arc B580'):
            self.assertEqual(detect.choose(inventory(name),self.recipe)['backend'],'cpu')

    def test_driver_comparison_is_numeric_and_missing_or_old_versions_use_cpu(self):
        for driver in ('32.0.23027.2004','31.99.99999.99999','unknown','32.0.23027',''):
            decision=detect.choose(inventory(driver=driver),self.recipe)
            self.assertEqual(decision['backend'],'cpu');self.assertIn('driver',decision['reason'])
        self.assertEqual(detect.choose(inventory(driver='32.0.31041.5005'),self.recipe)['backend'],'rocm')

    def test_disabled_multiple_server_and_windows10_adapters_use_cpu(self):
        cases=[]
        data=inventory();data['gpus'][0]['healthy']=False;cases.append(data)
        data=inventory();data['gpus']*=2;cases.append(data)
        data=inventory();data['desktop']=False;cases.append(data)
        data=inventory();data['windowsBuild']=19045;cases.append(data)
        for data in cases:self.assertEqual(detect.choose(data,self.recipe)['backend'],'cpu')

    def test_virtual_monitor_does_not_prevent_nvidia_and_nvidia_encoder_must_pass(self):
        data=inventory();data['gpus'] += [dict(vendorId='10DE',healthy=True),dict(vendorId='',healthy=True)]
        self.assertEqual(detect.choose(data,self.recipe,nvidia_ready=True)['backend'],'cuda')
        self.assertEqual(detect.choose(data,self.recipe,nvidia_ready=False)['backend'],'rocm')
        data['gpus'][1]['healthy']=False
        self.assertEqual(detect.choose(data,self.recipe,nvidia_ready=True)['backend'],'rocm')

    def test_inventory_failure_uses_cpu_but_known_arm_is_rejected(self):
        self.assertEqual(detect.choose(dict(state='unavailable',gpus=[]),self.recipe)['backend'],'cpu')
        with self.assertRaisesRegex(ValueError,'x64'):detect.choose(dict(state='unavailable',architecture='unsupported'),self.recipe)

    def test_explicit_amd_does_not_silently_relabel_cpu_as_acceleration(self):
        with self.assertRaisesRegex(ValueError,'Select Automatic'):
            setup.selection('rocm','ffmpeg',self.manifest,inventory('AMD Radeon Graphics'))

    def test_all_amd_assets_have_https_hash_pins_and_keep_checkpoint_manifest(self):
        self.assertEqual(len(self.recipe['assets']),6)
        for asset in self.recipe['assets']:
            self.assertTrue(asset['url'].startswith('https://repo.radeon.com/'))
            self.assertRegex(asset['sha256'],'^[a-f0-9]{64}$')
        profile=setup.profile_manifest(self.manifest,'rocm')
        value=setup.plan(Path('separate-engine'),profile,True)
        self.assertEqual(value['models'],self.manifest['models'])
        self.assertNotIn('rife',[r['name'] for r in value['repositories']])
        self.assertFalse(value['startsConversion']);self.assertFalse(value['driverInstalledAutomatically'])

    def test_failed_auto_gpu_startup_installs_and_checks_cpu_once(self):
        prepare=Mock(side_effect=lambda backend:backend+'-python')
        def validate(python,backend):
            if backend=='rocm':raise setup.StartupError('No compatible GPU')
            return dict(ready=True)
        warnings=[]
        result=setup.choose_working_backend('auto','rocm',prepare,validate,warnings)
        self.assertEqual(result,('cpu','cpu-python',dict(ready=True)))
        self.assertEqual([call.args[0] for call in prepare.call_args_list],['rocm','cpu'])
        self.assertIn('startup failed',warnings[0])

    def test_package_install_and_download_failures_allow_auto_cpu_fallback(self):
        for error in (subprocess.CalledProcessError(1,['pip']),setup.DownloadError('network'),OSError('DLL')):
            prepare=Mock(side_effect=[error,'cpu-python']);validate=Mock(return_value=dict(ready=True))
            self.assertEqual(setup.choose_working_backend('auto','cuda',prepare,validate,[])[0],'cpu')
            validate.assert_called_once_with('cpu-python','cpu')

    def test_integrity_failures_explicit_gpu_and_failed_cpu_never_report_ready(self):
        for error in (setup.IntegrityError('hash mismatch'),ValueError('foreign path')):
            prepare=Mock(side_effect=error)
            with self.assertRaises(type(error)):setup.choose_working_backend('auto','rocm',prepare,Mock(),[])
            self.assertEqual(prepare.call_count,1)
        with self.assertRaises(setup.StartupError):
            setup.choose_working_backend('rocm','rocm',Mock(return_value='python'),Mock(side_effect=setup.StartupError('GPU')),[])
        with self.assertRaises(setup.StartupError):
            setup.choose_working_backend('auto','rocm',Mock(return_value='python'),Mock(side_effect=setup.StartupError('CPU also failed')),[])

    def test_managed_auto_amd_requires_matching_runtime_and_gpu_proof(self):
        torch=SimpleNamespace(__version__='test-torch',version=SimpleNamespace(hip='test'),cuda=SimpleNamespace(
            is_available=lambda:True,device_count=lambda:1,get_device_name=lambda _: 'AMD Radeon RX 7900 XTX'))
        config=dict(backend='auto',managedBackend='rocm',runtimeProbePassed=True,setupTorchVersion='test-torch',setupGpuName='AMD Radeon RX 7900 XTX')
        with patch.object(hardware,'IS_MAC',False),patch.object(hardware,'IS_WINDOWS',True),patch.object(hardware,'WINDOWS_BUILD',22631):
            self.assertEqual(hardware.resolve(config,torch),'rocm')
            for changes in (dict(runtimeProbePassed=False),dict(setupTorchVersion='old'),dict(setupGpuName='AMD Radeon RX 9070 XT'),dict(setupGpuName='')):
                self.assertEqual(hardware.resolve(dict(config,**changes),torch),'cpu')
            self.assertEqual(hardware.resolve(dict(backend='auto'),torch),'cpu')

    def test_long_amd_paths_request_a_shorter_location_without_policy_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            wheel=Path(folder)/'sdk.whl'
            with zipfile.ZipFile(wheel,'w') as archive:archive.writestr('library/'+'kernel-name-'*12+'.dat','fixture')
            setup.check_wheel_paths([wheel],Path('D:/short'))
            with self.assertRaisesRegex(setup.StartupError,'shorter engine location'):
                setup.check_wheel_paths([wheel],Path('D:/'+('long-folder/'*15)))

    def test_real_child_package_diagnostics_are_captured_on_failure(self):
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            setup.execute([sys.executable,'-c','import sys; print("actionable package error"); sys.exit(1)'])
        self.assertIn('actionable package error',failure.exception.output)


if __name__=='__main__':unittest.main()
