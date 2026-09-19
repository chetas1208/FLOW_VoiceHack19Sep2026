"""Graph-derived *drafts*, never executable assertions until owner approval."""
import json
from services.graph.graph import Graph


def suggest(graph, project, version, max_drafts=50):
    prefix = f'{project}:{version}:'
    with graph.connect() as db:
        records = db.execute("SELECT id,properties,provenance FROM nodes WHERE kind='route_hint' AND id LIKE ? ORDER BY id LIMIT ?",
                             (prefix+'%', max_drafts)).fetchall()
    output=[]
    for identifier, properties, provenance in records:
        data=json.loads(properties)
        # A status code, authorization requirement, or business assertion is
        # not knowable from a regex source hint alone.
        output.append({'id':'draft-'+str(len(output)+1), 'route':data['path'],
                       'method':data['method'], 'provenance':provenance,
                       'status':'PROPOSED_REQUIRES_OWNER_APPROVAL',
                       'required_owner_inputs':['approved staging origin', 'authorized identity',
                                                'initial state fixture', 'expected outcome oracle',
                                                'cleanup and side-effect policy']})
    return output
