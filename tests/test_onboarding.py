import os
import tempfile
import importlib
from pathlib import Path
from fastapi.testclient import TestClient


def test_onboarding_routes_need_approval_and_path_restriction():
    with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
        root=Path(temp)
        (root/'myapp').mkdir()
        (root/'myapp'/'api.ts').write_text('router.get("/health", handler);\nrouter.post("/users", signup);')
        (root/'escape').symlink_to(outside, target_is_directory=True)
        old={k:os.environ.get(k) for k in ('QA_DATA_DIR','QA_PROJECTS_ROOT','QA_API_TOKEN')}
        try:
            os.environ['QA_DATA_DIR']=str(root/'results')
            os.environ['QA_PROJECTS_ROOT']=temp
            os.environ.pop('QA_API_TOKEN',None)
            from services.platform import api
            importlib.reload(api)
            client=TestClient(api.app)
            response=client.post('/projects/discover',json={'relative_path':'myapp',
                                                  'project_id':'p','version':'v1'})
            assert response.status_code==200,response.text
            value=response.json()
            assert value['discovery']['routes']==2
            assert value['tests_automatically_approved'] is False
            assert all(s['status']=='PROPOSED_REQUIRES_OWNER_APPROVAL' for s in value['proposed_scenarios'])
            assert client.post('/projects/discover',json={'relative_path':'../../etc'}).status_code==422
            assert client.post('/projects/discover',json={'relative_path':'escape'}).status_code==422
        finally:
            for key,value in old.items():
                if value is None:os.environ.pop(key,None)
                else:os.environ[key]=value
