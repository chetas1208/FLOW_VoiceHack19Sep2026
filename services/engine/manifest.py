"""Strict, data-only scenario validation. No arbitrary Python or shell execution."""
import ipaddress
import os
from urllib.parse import urlsplit
from jsonschema import Draft202012Validator

SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'type': 'object', 'additionalProperties': False,
    'required': ['id', 'base_url', 'steps', 'assertions'],
    'properties': {
        'id': {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{1,80}$'},
        'project_id': {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{1,80}$'},
        'kind': {'enum': ['fullstack', 'agentic', 'hybrid']},
        'version': {'type': 'string', 'maxLength': 128},
        'base_url': {'type': 'string', 'maxLength': 500},
        'oracle_base_url': {'type': 'string', 'maxLength': 500},
        'auth_env': {'type': 'string', 'pattern': '^QA_TARGET_TOKEN_[A-Z0-9_]{1,60}$'},
        'oracle_auth_env': {'type': 'string', 'pattern': '^QA_TARGET_TOKEN_[A-Z0-9_]{1,60}$'},
        'steps': {'type': 'array', 'minItems': 1, 'maxItems': 25, 'items': {'$ref': '#/$defs/step'}},
        'assertions': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': {'$ref': '#/$defs/assertion'}},
        'timeout_seconds': {'type': 'number', 'minimum': 0.1, 'maximum': 20},
    },
    '$defs': {
        'step': {'type': 'object', 'additionalProperties': False, 'required': ['name', 'method', 'path'],
                 'properties': {
                     'name': {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{1,80}$'},
                     'method': {'enum': ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']},
                     'target': {'enum': ['application', 'oracle']},
                     'path': {'type': 'string', 'pattern': '^/[^?#]*$', 'maxLength': 500},
                     'json': {'type': ['object', 'array', 'string', 'number', 'boolean', 'null']},
                     'headers': {'type': 'object', 'maxProperties': 10,
                                 'propertyNames': {'pattern': '^(Content-Type|Accept|X-Test-[a-zA-Z0-9-]+)$'},
                                 'additionalProperties': {'type': 'string', 'maxLength': 256}}
                 }},
        'assertion': {'type': 'object', 'additionalProperties': False,
                      'required': ['id', 'step', 'operator', 'expected'],
                      'properties': {
                          'id': {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{1,80}$'},
                          'step': {'type': 'string', 'minLength': 1, 'maxLength': 80},
                          'pointer': {'type': 'string', 'maxLength': 512},
                          'operator': {'enum': ['equals', 'not_equals', 'contains', 'length_equals', 'exists', 'status_equals', 'less_or_equal']},
                          'expected': {},
                      }}
    }
}


def approved_base_url(url):
    """Default loopback-only; optional explicit HTTPS host allowlist for authorized pilots.

    DNS re-resolution / egress isolation cannot be guaranteed by this validator:
    remote hosts require infrastructure-level egress policies before production use.
    """
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('base_url must be an HTTP(S) origin without credentials')
    if parts.path not in ('', '/') or parts.query or parts.fragment:
        raise ValueError('base_url must be an origin without path, query, or fragment')
    if parts.hostname in ('localhost', '127.0.0.1', '::1'):
        return url.rstrip('/')
    try:
        ip = ipaddress.ip_address(parts.hostname)
        if ip.is_loopback:
            return url.rstrip('/')
    except ValueError:
        pass
    allowed = {host.strip().lower() for host in os.getenv('QA_ALLOWED_HTTPS_HOSTS', '').split(',') if host.strip()}
    if parts.scheme != 'https' or parts.hostname.lower() not in allowed:
        raise ValueError('remote targets require HTTPS and an explicit QA_ALLOWED_HTTPS_HOSTS entry')
    return url.rstrip('/')


def validate_manifest(value):
    Draft202012Validator(SCHEMA).validate(value)
    for field in ('auth_env', 'oracle_auth_env'):
        if field in value and not os.getenv(value[field]):
            raise ValueError(f'{field} requires a configured environment secret')
    if 'oracle_auth_env' in value and 'oracle_base_url' not in value:
        raise ValueError('oracle_auth_env requires oracle_base_url')
    approved_base_url(value['base_url'])
    if 'oracle_base_url' in value:
        approved_base_url(value['oracle_base_url'])
    for step in value['steps']:
        if step.get('target') == 'oracle' and ('oracle_base_url' not in value or step['method'] != 'GET'):
            raise ValueError('oracle requests require oracle_base_url and GET')
        if step['method'] == 'DELETE' and os.getenv('QA_ALLOW_DESTRUCTIVE') != '1':
            raise ValueError('DELETE requires QA_ALLOW_DESTRUCTIVE=1')
    if len({s['name'] for s in value['steps']}) != len(value['steps']):
        raise ValueError('duplicate step name')
    steps = {s['name'] for s in value['steps']}
    if len({a['id'] for a in value['assertions']}) != len(value['assertions']):
        raise ValueError('duplicate assertion ID')
    for assertion in value['assertions']:
        if assertion['step'] not in steps:
            raise ValueError('assertion references unknown step: ' + assertion['step'])
        if assertion['operator'] == 'status_equals' and assertion.get('pointer'):
            raise ValueError('status assertion must not specify pointer')
        pointer = assertion.get('pointer', '')
        if pointer and (not pointer.startswith('/') or '~' in pointer.replace('~0', '').replace('~1', '')):
            raise ValueError('invalid JSON Pointer')
    return value
