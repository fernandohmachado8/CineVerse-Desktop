import hashlib
import importlib.util
import io
import json
from pathlib import Path
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

    def test_existing_correct_download_needs_no_network(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'asset';file.write_bytes(b'verified')
            asset={'sha256':hashlib.sha256(b'verified').hexdigest()}
            self.assertEqual(setup.verified_download(asset,file),file)


if __name__=='__main__':unittest.main()
