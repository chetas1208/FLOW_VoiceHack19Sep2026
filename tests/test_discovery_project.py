import tempfile
from pathlib import Path
from services.graph.graph import Graph
from services.discovery.project import discover_project


def test_python_js_ts_route_and_provenance():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        (root/'server.py').write_text('@app.get("/health")\ndef health():\n  pass\n')
        (root/'api.ts').write_text('export function getStatus() {}\nrouter.post("/users", handler);')
        (root/'app'/'profile').mkdir(parents=True)
        (root/'app'/'profile'/'page.tsx').write_text('export function Profile() {return null;}')
        g=Graph(root/'g.sqlite3')
        result=discover_project(root,g,project='project-a',version='v1')
        assert result['files']==3
        assert result['routes']>=3
        assert result['symbols']>=3
        assert result['truncated'] is False
        with g.connect() as db:
            hints=db.execute("SELECT COUNT(*) FROM nodes WHERE kind='route_hint'").fetchone()[0]
            assert hints>=3
            assert db.execute("SELECT COUNT(*) FROM edges WHERE provenance='' ").fetchone()[0]==0


def test_no_symlink_escape_and_bounded_scan():
    with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
        root=Path(temp)
        (Path(outside)/'secret.py').write_text('def secret():pass')
        (root/'steal.py').symlink_to(Path(outside)/'secret.py')
        (root/'ok.py').write_text('def ok():pass')
        (root/'other.py').write_text('def other():pass')
        g=Graph(root/'g.sqlite3')
        result=discover_project(root,g,limit=1)
        assert result['files']==1
        assert result['truncated'] is True
        with g.connect() as db:
            assert not db.execute("SELECT id FROM nodes WHERE id LIKE '%secret%'").fetchone()
