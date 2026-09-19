"""Rank-free provenance lookup: map observed HTTP paths to static source hints.

Never guesses cause, executes repository code, or reads source outside the graph.
Static route declarations are candidate locations only, not confirmed call paths.
"""
import json


def attach_candidates(graph, project, version, findings, events):
    if graph is None or not findings:
        return findings
    with graph.connect() as db:
        routes = db.execute('''SELECT r.properties, r.provenance, f.properties, f.provenance
            FROM nodes AS r JOIN edges AS e ON e.target=r.id AND e.relation='DECLARES_ROUTE'
            JOIN nodes AS f ON f.id=e.source
            WHERE r.kind='route_hint' AND r.version=? AND r.id LIKE ?
            ORDER BY r.id LIMIT 2000''', (version, f'{project}:{version}:%')).fetchall()
    for finding in findings:
        # The window refers only to observed network events; guessed source files
        # without an observed matching route never receive an attribution.
        network = {(e.get('method'), e.get('path')) for e in events
                   if e['source'] == 'network' and e.get('method') and e.get('path')
                   and e['seq'] <= finding.get('event_seq_end', 0)
                   and e['seq'] >= max(0, finding.get('event_seq_start', 0) - 25)}
        candidates = []
        for route_properties, route_prov, file_properties, file_prov in routes:
            route = json.loads(route_properties)
            if (route.get('method'), route.get('path')) not in network:
                continue
            file = json.loads(file_properties)
            candidates.append({'file': file['path'], 'route': route['path'],
                               'method': route['method'], 'route_provenance': route_prov,
                               'source_sha256': file['sha256'], 'confirmed_cause': False})
            if len(candidates) >= 5: break
        finding['source_candidates'] = candidates
    return findings
