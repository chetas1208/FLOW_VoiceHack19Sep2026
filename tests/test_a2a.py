import importlib
import os
import tempfile
import unittest
from fastapi.testclient import TestClient


class A2ALimitedAdapterTests(unittest.TestCase):
    def test_agent_card_and_benchmark_rpc(self):
        with tempfile.TemporaryDirectory() as temp:
            previous = os.environ.get('QA_DATA_DIR'), os.environ.get('QA_API_TOKEN')
            try:
                os.environ['QA_DATA_DIR'] = temp
                os.environ['QA_API_TOKEN'] = 'testing-only-token'
                from services.platform import api, a2a
                importlib.reload(api)
                client = TestClient(api.app)
                self.assertEqual(client.get('/.well-known/agent-card.json').status_code, 401)
                headers={'x-qa-api-token':'testing-only-token'}
                card=client.get('/.well-known/agent-card.json',headers=headers).json()
                self.assertEqual(card['protocolVersion'], '0.3.0')
                self.assertFalse(card['capabilities']['streaming'])
                payload={'jsonrpc':'2.0', 'id':1,'method':'message/send',
                         'params':{'message':{'role':'user','parts':[{'kind':'text','text':'run qa benchmark'}],
                                              'messageId':'test-1'}}}
                response=client.post('/a2a',json=payload,headers=headers)
                self.assertEqual(response.status_code,200,response.text)
                task=response.json()['result']
                self.assertEqual(task['status']['state'],'completed')
                get=client.post('/a2a',json={'jsonrpc':'2.0','id':2,'method':'tasks/get',
                                             'params':{'id':task['id']}},headers=headers)
                self.assertEqual(get.json()['result']['id'],task['id'])
                bad=client.post('/a2a',json={'jsonrpc':'2.0','id':3,'method':'unknown'},headers=headers)
                self.assertEqual(bad.json()['error']['code'],-32601)
                bad=client.post('/a2a',json={'jsonrpc':'2.0','id':4,'method':'message/send',
                                             'params':{'message':{'role':'user','parts':[{'kind':'text','text':'delete server'}]}}},headers=headers)
                self.assertEqual(bad.json()['error']['code'],-32602)
            finally:
                if previous[0] is None:os.environ.pop('QA_DATA_DIR',None)
                else:os.environ['QA_DATA_DIR']=previous[0]
                if previous[1] is None:os.environ.pop('QA_API_TOKEN',None)
                else:os.environ['QA_API_TOKEN']=previous[1]
