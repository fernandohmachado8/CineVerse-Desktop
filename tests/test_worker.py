import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'worker'))
spec=importlib.util.spec_from_file_location('worker',Path(__file__).parents[1]/'worker/worker.py')
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)

class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.media={'fps':23.976,'duration':10.01,'hdr':False,'sar':'1:1'}
        self.request={'strength':3,'fpsMode':'original','preview':True,'previewStart':2,'previewSeconds':10}
    def test_preview_clips_to_end(self):
        self.assertEqual(worker.validate(self.request,self.media),(3,2,8.01))
    def test_full_export_ignores_preview_window(self):
        self.request['preview']=False
        self.assertEqual(worker.validate(self.request,self.media),(3,0,10.01))
    def test_strength_rejects_nan_and_out_of_range(self):
        for value in (float('nan'),float('inf'),-1,6):
            with self.subTest(value=value), self.assertRaises(ValueError):
                worker.validate({**self.request,'strength':value},self.media)
    def test_preview_start_outside_video(self):
        for value in (-1,10.01,float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                worker.validate({**self.request,'previewStart':value},self.media)
    def test_hdr_fails_explicitly(self):
        with self.assertRaisesRegex(ValueError,'HDR'):
            worker.validate(self.request,{**self.media,'hdr':True})
    def test_unavailable_gpu_paths_are_actionable(self):
        with self.assertRaisesRegex(ValueError,'Engine settings'):
            worker.check({},gpu=False)
    def test_unsupported_fps_modes(self):
        with self.assertRaises(ValueError):worker.validate({**self.request,'fpsMode':'120'},self.media)
    def test_anamorphic_rejected(self):
        with self.assertRaisesRegex(ValueError,'square-pixel'):
            worker.validate(self.request,{**self.media,'sar':'4:3'})
    def test_missing_strength_defaults_to_preferred_1_5(self):
        request={k:v for k,v in self.request.items() if k!='strength'}
        self.assertEqual(worker.validate(request,self.media)[0],1.5)
        self.assertEqual(worker.validate({**request,'resumeJob':'legacy/job.json'},self.media)[0],3)
    def test_unknown_gap_filling_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'gap filling'):
            worker.validate({**self.request,'stereoMethod':'unknown'},self.media)

if __name__=='__main__':unittest.main()
