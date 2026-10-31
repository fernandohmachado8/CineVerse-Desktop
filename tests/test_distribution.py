import hashlib
import importlib.util
import io
import json
import shutil
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('setup_engine', ROOT/'scripts/setup_engine.py')
setup = importlib.util.module_from_spec(spec); spec.loader.exec_module(setup)


class DistributionTests(unittest.TestCase):
    def test_plan_is_explicit_and_does_not_start_work(self):
        manifest = json.loads(setup.MANIFEST.read_text())
        value = setup.plan(Path('engine-example'), manifest, True)
        self.assertFalse(value['startsConversion'])
        self.assertFalse(value['driverInstalledAutomatically'])
        self.assertGreater(len(value['models']), 5)

    def test_cpu_plan_has_cpu_wheels_and_omits_unused_rife(self):
        manifest = json.loads(setup.MANIFEST.read_text())
        manifest = {**manifest, **manifest['cpuProfile']}
        value = setup.plan(Path('engine-example'), manifest, True)
        self.assertEqual(value['processingBackend'], 'cpu')
        self.assertTrue(value['torch'].endswith('+cpu'))
        self.assertTrue(value['torchIndex'].endswith('/cpu'))
        self.assertNotIn('rife', [r['name'] for r in value['repositories']])
        self.assertEqual(value['models'], manifest['models'])

    def test_automatic_setup_assets_are_pinned_and_sources_need_no_git(self):
        manifest=json.loads(setup.MANIFEST.read_text(encoding='utf8'))
        for asset in [manifest['bootstrapPython'],manifest['cpuDriver']]+[r['archive'] for r in manifest['repositories']]:
            self.assertRegex(asset['sha256'],'^[a-f0-9]{64}$')
            self.assertTrue(asset['url'].startswith('https://'))
        self.assertIn('python-build-standalone',manifest['bootstrapPython']['url'])

    def test_commit_archive_installs_without_git_and_is_retryable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);archive=root/'source.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('source/LICENSE','notice');z.writestr('source/code.py','original')
            asset=dict(name='demo',directory='tools/demo',commit='a'*40,archive=dict(sha256=setup.digest(archive)))
            with patch.object(setup,'verified_download',return_value=archive),patch.object(setup,'execute') as execute:
                setup.checkout(asset,root);setup.checkout(asset,root);execute.assert_not_called()
            self.assertEqual((root/'tools/demo/code.py').read_text(),'original')
            self.assertEqual((root/'tools/demo/LICENSE').read_text(),'notice')
            with self.assertRaises(ValueError):setup.checkout({**asset,'commit':'b'*40},root)

    def test_archive_submodule_requirement_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);archive=root/'source.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('source/.gitmodules','[submodule "missing"]')
            asset=dict(name='demo',directory='tools/demo',commit='a'*40,archive=dict(sha256=setup.digest(archive)))
            with patch.object(setup,'verified_download',return_value=archive),self.assertRaisesRegex(ValueError,'submodules'):
                setup.checkout(asset,root)
            self.assertFalse((root/'tools/demo').exists())

    def test_setup_refuses_foreign_folder_and_runtime_marker_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'keep.txt').write_text('preserve')
            manifest={'bootstrapPython':{'sha256':'a'*64}}
            with self.assertRaisesRegex(ValueError,'empty'):setup.claim_install_root(root,manifest)
            self.assertEqual((root/'keep.txt').read_text(),'preserve')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);setup.claim_install_root(root,manifest);setup.claim_install_root(root,manifest)
            with self.assertRaisesRegex(ValueError,'runtime'):setup.claim_install_root(root,{'bootstrapPython':{'sha256':'b'*64}})

    def test_auto_profile_probes_encoder_before_choosing_wheels(self):
        from types import SimpleNamespace
        for code,expected in ((0,'cuda'),(1,'cpu')):
            with patch.object(setup.subprocess,'run',return_value=SimpleNamespace(returncode=code)):
                self.assertEqual(setup.select_profile('auto','ffmpeg'),expected)
        with patch.object(setup.subprocess,'run') as probe:
            self.assertEqual(setup.select_profile('cpu','ffmpeg'),'cpu');probe.assert_not_called()

    def test_every_upstream_checkout_and_asset_is_pinned(self):
        manifest = json.loads(setup.MANIFEST.read_text())
        for repo in manifest['repositories']:
            self.assertRegex(repo['commit'], '^[a-f0-9]{40}$')
        for asset in manifest['models'] + [manifest['ffmpeg'], manifest['sensor'], manifest['rifeModel']]:
            self.assertRegex(asset['sha256'], '^[a-f0-9]{64}$')
            self.assertTrue(asset['url'].startswith('https://'))

    def test_archive_traversal_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('../outside', '/outside', 'D:/outside', '..\\outside'):
                file=Path(folder)/'bad.zip'
                with zipfile.ZipFile(file,'w') as z: z.writestr(name,'bad')
                with self.subTest(name=name), self.assertRaises(ValueError):
                    setup.safe_extract(file, Path(folder)/'safe')
            link=zipfile.ZipInfo('link');link.external_attr=0o120777 << 16
            with zipfile.ZipFile(file,'w') as z: z.writestr(link,'../outside')
            with self.assertRaises(ValueError): setup.safe_extract(file, Path(folder)/'safe')

    def test_archive_long_paths_work_without_changing_windows_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);archive=root/'long.zip';name='/'.join(['nestedpart']*28)+'/keep.txt'
            with zipfile.ZipFile(archive,'w') as z:z.writestr(name,'long path supported')
            setup.safe_extract(archive,root/'out')
            self.assertEqual(Path(setup.long_path(root/'out'/name)).read_text(),'long path supported')
            target=(root/'out').resolve()
            self.assertEqual(target.parent,root.resolve())
            shutil.rmtree(setup.long_path(target))

    def test_valid_archive_keeps_its_license_and_files(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'good.zip'
            with zipfile.ZipFile(file,'w') as z:
                z.writestr('package/LICENSE','upstream notice');z.writestr('package/file.txt','content')
            setup.safe_extract(file,Path(folder)/'safe')
            self.assertEqual((Path(folder)/'safe/package/LICENSE').read_text(),'upstream notice')

    def test_existing_bad_download_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'asset';file.write_bytes(b'preserve')
            with self.assertRaises(ValueError):setup.verified_download({'sha256':'0'*64},file)
            self.assertEqual(file.read_bytes(),b'preserve')

    def test_transient_download_failure_is_retried_and_hash_checked(self):
        from urllib.error import URLError
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'verified';response=io.BytesIO(b'original');response.headers={'Content-Length':'8'}
            asset={'url':'https://example.invalid/asset','sha256':hashlib.sha256(b'original').hexdigest()}
            with patch.object(setup.urllib.request,'urlopen',side_effect=[URLError('reset'),response]) as fetch,patch.object(setup.time,'sleep'):
                setup.verified_download(asset,target)
            self.assertEqual(fetch.call_count,2);self.assertEqual(target.read_bytes(),b'original')

    def test_existing_correct_download_needs_no_network(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'asset';file.write_bytes(b'verified')
            asset={'sha256':hashlib.sha256(b'verified').hexdigest()}
            self.assertEqual(setup.verified_download(asset,file),file)


if __name__=='__main__':unittest.main()
