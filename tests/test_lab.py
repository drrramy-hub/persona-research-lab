import copy
import io
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
import core
import foundry
from app import Handler

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = json.loads((ROOT/'examples/synthetic-study.json').read_text())
ANALYSIS = json.loads((ROOT/'examples/demo-analysis.json').read_text())
ENV = {'FOUNDRY_ENDPOINT':'https://example.openai.azure.com/openai/v1',
       'FOUNDRY_API_KEY':'test-only', 'FOUNDRY_DEPLOYMENT':'test-model'}

def data(**changes):
    return dict({'action':'analyse','mode':'demo','language':'English','context':'Energy service research',
                 'evidence':copy.deepcopy(EVIDENCE),'analysis':copy.deepcopy(ANALYSIS),
                 'reviewed':True,'evidence_fingerprint':core.fingerprint(EVIDENCE),
                 'question':'What should we investigate?', 'persona_id':'P1'}, **changes)

class EvidenceTests(unittest.TestCase):
    def test_demo_offline(self):
        with patch('core.complete',side_effect=AssertionError('Cloud called')):
            self.assertEqual(len(core.run(data())['analysis']['personas']),2)
            self.assertEqual(len(core.run(data(action='compare'))['responses']),2)

    def test_demo_rejects_other_evidence(self):
        altered=copy.deepcopy(EVIDENCE);altered[0]['text']='Different source'
        with self.assertRaisesRegex(ValueError,'Demo works only'):core.run(data(evidence=altered))

    def test_duplicate_source_ids(self):
        with self.assertRaisesRegex(ValueError,'unique'):core.evidence([EVIDENCE[0],EVIDENCE[0]])

    def test_unknown_source_rejected(self):
        a=copy.deepcopy(ANALYSIS);a['personas'][0]['evidence_ids']=['E999']
        with self.assertRaisesRegex(ValueError,'unknown'):core.analysis(a,core.evidence(EVIDENCE))

    def test_fabricated_quote_rejected(self):
        a=copy.deepcopy(ANALYSIS);a['themes'][0]['quotes'][0]['text']='An invented quotation'
        with self.assertRaisesRegex(ValueError,'does not match'):core.analysis(a,core.evidence(EVIDENCE))

    def test_review_required_before_model(self):
        with patch('core.complete',side_effect=AssertionError('Cloud called')):
            with self.assertRaisesRegex(ValueError,'Review and approve'):core.run(data(action='ask',mode='live',reviewed=False))

    def test_changed_evidence_requires_review(self):
        with self.assertRaisesRegex(ValueError,'changed'):core.run(data(action='ask',evidence_fingerprint='old'))

    def test_review_edits_are_checked_offline(self):
        with patch('core.complete',side_effect=AssertionError('Cloud called')):
            self.assertEqual(core.run(data(action='review',mode='live',reviewed=False))['analysis'],ANALYSIS)

    def test_persona_receives_only_its_sources(self):
        answer={'basis':'evidence-informed','response':'The sample suggests cost clarity matters.',
                'evidence_ids':['E1'],'hypotheses':[],'follow_up_questions':['Which costs are unclear?']}
        with patch('core.complete',return_value=(answer,{'deployment':'mock'})) as call:
            result=core.run(data(action='ask',mode='live'))
            self.assertTrue(result['responses'][0]['simulation'])
            self.assertEqual([x['id'] for x in call.call_args.args[1]['evidence']],['E1','E2'])

    def test_cross_persona_citation_rejected(self):
        answer={'basis':'evidence-informed','response':'Unsupported for this persona.',
                'evidence_ids':['E4'],'hypotheses':[],'follow_up_questions':['Why?']}
        with self.assertRaisesRegex(ValueError,'outside'):core.answer(answer,core.evidence(EVIDENCE),['E1','E2'])

    def test_live_analysis_rejects_bad_output(self):
        with patch('core.complete',return_value=({'themes':[]},{'deployment':'mock'})):
            with self.assertRaises(ValueError):core.run(data(mode='live'))

class AdapterTests(unittest.TestCase):
    def test_request_configuration(self):
        payload={'status':'completed','output':[{'content':[{'type':'output_text','text':'{"ok":true}'}]}]}
        with patch.dict(os.environ,ENV,clear=True),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as call:
            result,meta=foundry.complete('instructions',{'test':'input'})
            self.assertEqual(result,{'ok':True});self.assertEqual(meta['deployment'],'test-model')
            body=json.loads(call.call_args.args[0].data)
            self.assertFalse(body['store']);self.assertEqual(body['model'],'test-model')

    def test_incomplete_response_rejected(self):
        with patch.dict(os.environ,ENV,clear=True),patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"status":"incomplete"}')):
            with self.assertRaisesRegex(RuntimeError,'did not complete'):foundry.complete('x',{})

    def test_non_json_rejected(self):
        payload={'status':'completed','output':[{'content':[{'type':'output_text','text':'not json'}]}]}
        with patch.dict(os.environ,ENV,clear=True),patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
            with self.assertRaisesRegex(RuntimeError,'valid JSON'):foundry.complete('x',{})

    def test_endpoint_restriction(self):
        with patch.dict(os.environ,dict(ENV,FOUNDRY_ENDPOINT='https://evil.example/openai/v1'),clear=True):
            with self.assertRaises(ValueError):foundry.configuration()

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def test_ui_assets(self):
        for path in ['/','/app.js','/style.css','/api/example']:
            with urllib.request.urlopen(self.url+path) as response:self.assertEqual(response.status,200)
    def test_end_to_end_demo(self):
        request=urllib.request.Request(self.url+'/api/generate',data=json.dumps(data()).encode(),headers={'Origin':self.url,'Content-Type':'application/json'})
        with urllib.request.urlopen(request) as response:self.assertEqual(json.load(response)['mode'],'demo')
    def test_cross_origin_rejected(self):
        request=urllib.request.Request(self.url+'/api/generate',data=b'{}',headers={'Origin':'https://untrusted.example','Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code,403)

if __name__=='__main__':unittest.main()
