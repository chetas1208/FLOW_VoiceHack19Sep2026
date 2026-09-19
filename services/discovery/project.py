"""Bounded, provenance-backed multi-language discovery (not full program analysis).

Python: AST extraction. JS/TS: conservative regex hints explicitly marked as
regex-derived, never promoted to verified runtime call relationships.
"""
import ast
import hashlib
import os
import re
from pathlib import Path
from services.graph.graph import Graph

EXTENSIONS = {'.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs'}
EXCLUDED = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', 'dist', 'build', '.next', 'target'}
JS_SYMBOL = re.compile(r'\b(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][A-Za-z0-9_$]*)\b')
JS_ROUTE = re.compile(r'\b(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]')
PY_ROUTE = re.compile(r'@(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*[\'\"]([^\'\"]+)')
AGENT_HINTS = re.compile(r'\b(langgraph|langchain|crewai|autogen|agent|tool|mcp|openai)\b', re.I)


def discover_project(repo, graph, *, project='local', version='local', limit=3000):
    repo = Path(repo).resolve(strict=True)
    if not repo.is_dir() or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', project):
        raise ValueError('invalid project or repository')
    if not 1 <= limit <= 10000:
        raise ValueError('invalid discovery limit')
    files = symbols = routes = hints = 0
    skipped = []
    for directory, dirs, filenames in os.walk(repo, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not (Path(directory)/d).is_symlink())
        for name in sorted(filenames):
            file = Path(directory) / name
            if file.suffix not in EXTENSIONS or file.is_symlink() or not file.is_file():
                continue
            if files >= limit:
                return {'files': files, 'symbols': symbols, 'routes': routes, 'agent_hints': hints,
                        'truncated': True, 'skipped': skipped[:20]}
            try:
                if file.stat().st_size > 1_048_576:
                    skipped.append(str(file.relative_to(repo)))
                    continue
                contents = file.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                skipped.append(str(file.relative_to(repo)))
                continue
            rel = file.relative_to(repo).as_posix()
            digest = hashlib.sha256(contents.encode()).hexdigest()
            prefix = f'{project}:{version}'
            fid = f'{prefix}:file:{rel}'
            graph.node(fid, 'file', version, {'path': rel, 'sha256': digest, 'language': file.suffix}, 'source:sha256:' + digest)
            files += 1
            if file.suffix == '.py':
                try:
                    tree = ast.parse(contents)
                except SyntaxError:
                    skipped.append(rel + ':parse-error')
                    continue
                for item in ast.walk(tree):
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        symbol = f'{fid}:symbol:{item.lineno}:{item.name}'
                        prov = f'ast:{rel}:{item.lineno}:sha256:{digest}'
                        graph.node(symbol, 'symbol', version, {'name':item.name, 'line':item.lineno}, prov)
                        graph.edge(fid, symbol, 'DEFINES', version, prov)
                        symbols += 1
                route_matches = [(m.group(1).upper(), m.group(2), contents.count('\n', 0, m.start())+1)
                                 for m in PY_ROUTE.finditer(contents)]
            else:
                for m in JS_SYMBOL.finditer(contents):
                    line = contents.count('\n', 0, m.start()) + 1
                    symbol = f'{fid}:symbol:{line}:{m.group(1)}'
                    prov = f'regex-hint:{rel}:{line}:sha256:{digest}'
                    graph.node(symbol, 'symbol_hint', version, {'name':m.group(1), 'line':line}, prov)
                    graph.edge(fid, symbol, 'MAY_DEFINE', version, prov)
                    symbols += 1
                route_matches = [(m.group(1).upper(), m.group(2), contents.count('\n', 0, m.start())+1)
                                 for m in JS_ROUTE.finditer(contents)]
            if rel.startswith('app/') and rel.endswith(('page.tsx', 'page.jsx', 'page.js', 'page.ts')):
                # Next.js app-router route is a path convention, not runtime evidence.
                parts = rel.split('/')[:-1]
                route = '/' + '/'.join(p for p in parts[1:] if not p.startswith('('))
                route_matches.append(('PAGE', route, 1))
            for method, path, line in route_matches:
                rid = f'{prefix}:route:{method}:{path}'
                prov = f'static-route:{rel}:{line}:sha256:{digest}'
                graph.node(rid, 'route_hint', version, {'method':method, 'path':path}, prov)
                graph.edge(fid, rid, 'DECLARES_ROUTE', version, prov)
                routes += 1
            if AGENT_HINTS.search(contents):
                hint_id = f'{fid}:agent-hint'
                prov = 'keyword-hint:' + digest
                graph.node(hint_id, 'agent_hint', version, {'path':rel, 'confirmed':False}, prov)
                graph.edge(fid, hint_id, 'MAY_USE_AGENT_TECH', version, prov)
                hints += 1
    return {'files':files, 'symbols':symbols, 'routes':routes, 'agent_hints':hints,
            'truncated':False, 'skipped':skipped[:20]}
