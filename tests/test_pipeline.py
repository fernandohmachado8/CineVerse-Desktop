from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parents[1]/'worker'))
import pipeline
import worker


class LongMovieTests(unittest.TestCase):
    def setUp(self):
        self.media={'fps':24000/1001,'rate':'24000/1001','duration':10800.,'hdr':True,'sar':'1:1',
            'transfer':'smpte2084','primaries':'bt2020','pixelFormat':'yuv420p10le'}
        self.request={'source':'movie.mkv','outputDir':tempfile.gettempdir(),'strength':3,'fpsMode':'60','preview':False}
    def test_three_hour_hdr_is_not_limited_to_a_preview(self):
        self.assertEqual(worker.validate(self.request,self.media),(3,0,10800.))
    def test_hlg_and_unknown_hdr_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'HDR10'):
            worker.validate(self.request,{**self.media,'transfer':'arib-std-b67'})
    def test_full_movie_storage_budget_uses_whole_duration(self):
        with patch('pipeline.probe',return_value=self.media):
            p=pipeline.plan({},self.request)
        self.assertGreater(p['spaceBudgetBytes'],200*1024**3)
        self.assertEqual(p['targetFPS'],60)
    def test_preview_budget_uses_only_requested_window(self):
        with patch('pipeline.probe',return_value=self.media):
            p=pipeline.plan({},{**self.request,'preview':True,'previewSeconds':10,'previewStart':1500})
        self.assertEqual(p['seconds'],10)
        self.assertLess(p['spaceBudgetBytes'],2*1024**3)
    def test_resume_path_cannot_escape_job_root(self):
        root=Path(tempfile.gettempdir())/'cineverse-test'
        with self.assertRaises(ValueError):pipeline.resume_path(root,str(root/'other'/'job.json'))
        self.assertEqual(pipeline.resume_path(root,str(root/'.cineverse-jobs'/'abc'/'job.json')).parent.name,'abc')
    def test_failed_atomic_replace_keeps_previous_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'job.json';pipeline.atomic_json(p,{'completed':['prepare']})
            with patch('pipeline.os.replace',side_effect=PermissionError),self.assertRaises(PermissionError):
                pipeline.atomic_json(p,{'completed':['prepare','stereo']})
            self.assertEqual(json.loads(p.read_text()),{'completed':['prepare']})
    def test_preview_fingerprint_detects_replaced_input(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input';p.write_bytes(b'a'*100)
            before=pipeline.identity(p,False);p.write_bytes(b'b'*100)
            self.assertNotEqual(pipeline.identity(p,False),before)
    def test_active_process_is_detected_without_signalling_it(self):
        self.assertTrue(pipeline.alive(os.getpid()))
        self.assertFalse(pipeline.alive(0x7ffffffe))
    def test_guard_black_level_respects_full_range_sdr(self):
        self.assertEqual(pipeline.black_level(False,True),0)
        self.assertEqual(pipeline.black_level(False,False),16)
        self.assertEqual(pipeline.black_level(True,False),64)
        self.assertEqual(pipeline.black_level(True,True),0)
    def test_new_default_and_legacy_resume_do_not_change_saved_method(self):
        self.assertEqual(worker.stereo_method({}),'forward_inpaint')
        self.assertEqual(worker.stereo_method({'resumeJob':'saved/job.json'}),'row_flow_v3')
        old={'strength':3,'fpsMode':'60'}
        saved=pipeline.canonical_request(old,pipeline.LEGACY_VERSION)
        self.assertEqual(saved['stereoMethod'],'row_flow_v3')
        self.assertNotEqual(saved,pipeline.canonical_request(old))
        self.assertEqual(saved,pipeline.canonical_request({**old,'stereoMethod':'row_flow_v3','resumeJob':'saved/job.json'}))
        self.assertEqual(pipeline.canonical_request({},pipeline.LEGACY_VERSION)['strength'],3)
        self.assertEqual(pipeline.canonical_request({})['strength'],1.5)
    def test_neural_estimate_is_slower_than_previous_method(self):
        with patch('pipeline.probe',return_value=self.media):
            neural=pipeline.plan({},self.request)
            fast=pipeline.plan({},{**self.request,'stereoMethod':'row_flow_v3'})
        self.assertEqual(neural['stereoMethod'],'forward_inpaint')
        self.assertGreater(neural['estimatedSecondsLow'],fast['estimatedSecondsLow'])


if __name__=='__main__':unittest.main()
