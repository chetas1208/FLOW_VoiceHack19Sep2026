"""Declarative, bounded UI scenario contract; never accepts arbitrary executable code."""
import os
from pathlib import Path
from jsonschema import Draft202012Validator
from services.engine.manifest import approved_base_url

LOCATOR = {
    'type': 'object', 'additionalProperties': False,
    'required': ['by', 'value'],
    'properties': {
        'by': {'enum': ['role', 'text', 'test_id', 'label', 'placeholder', 'css',
                        'id', 'xpath', 'accessibility_id', 'class_name']},
        'value': {'type': 'string', 'minLength': 1, 'maxLength': 300},
        'exact': {'type': 'boolean'},
    },
}
ACTIONS = ['goto', 'click', 'fill', 'press', 'check', 'uncheck', 'select', 'hover',
           'wait_for', 'screenshot', 'assert_text', 'assert_url', 'assert_visible',
           'assert_count', 'assert_value', 'assert_title', 'assert_no_console_errors',
           'assert_no_http_errors', 'assert_log_contains', 'assert_trace_span',
           'assert_visual', 'assert_oracle', 'audit_accessibility', 'assert_no_page_errors', 'assert_no_server_errors']
SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'type': 'object', 'additionalProperties': False,
    'required': ['id', 'steps'],
    'properties': {
        'id': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{1,80}$'},
        'project_id': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{1,80}$'},
        'version': {'type': 'string', 'maxLength': 128},
        'origin': {'type': 'string', 'maxLength': 500},
        'driver': {'enum': ['web', 'webdriver']},
        'browser': {'enum': ['chromium', 'firefox', 'webkit']},
        'viewport': {'type': 'object', 'additionalProperties': False,
                     'required': ['width', 'height'],
                     'properties': {'width': {'type': 'integer', 'minimum': 320, 'maximum': 3840},
                                    'height': {'type': 'integer', 'minimum': 320, 'maximum': 3840}}},
        'webdriver_url': {'type': 'string', 'maxLength': 500},
        'capabilities': {'type': 'object', 'maxProperties': 25},
        'auth_env': {'type': 'string', 'pattern': '^QA_TARGET_TOKEN_[A-Z0-9_]{1,60}$'},
        'oracle_origin': {'type': 'string', 'maxLength': 500},
        'oracle_auth_env': {'type': 'string', 'pattern': '^QA_TARGET_TOKEN_[A-Z0-9_]{1,60}$'},
        'log_file': {'type': 'string', 'maxLength': 500},
        'log_messages': {'type': 'boolean'},
        'propagate_trace': {'type': 'boolean'},
        'allow_mutations': {'type': 'boolean'},
        'allow_destructive': {'type': 'boolean'},
        'screenshots': {'type': 'boolean'},
        'fixture_relay': {'type': 'boolean'},
        'timeout_ms': {'type': 'integer', 'minimum': 500, 'maximum': 30000},
        'steps': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': {'$ref': '#/$defs/step'}},
    },
    '$defs': {
        'step': {'type': 'object', 'additionalProperties': False, 'required': ['name', 'action'],
                 'properties': {
                     'name': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{1,80}$'},
                     'action': {'enum': ACTIONS},
                     'locator': LOCATOR,
                     'path': {'type': 'string', 'pattern': '^/[^#?]*$', 'maxLength': 500},
                     'value': {'type': ['string', 'integer', 'number', 'boolean'], 'maxLength': 2000},
                     'expected': {},
                     'timeout_ms': {'type': 'integer', 'minimum': 100, 'maximum': 30000},
                     'threshold': {'type': 'number', 'minimum': 0, 'maximum': 1},
                     'baseline': {'type': 'string', 'maxLength': 500},
                     'oracle_path': {'type': 'string', 'pattern': '^/[^#?]*$', 'maxLength': 500},
                     'pointer': {'type': 'string', 'maxLength': 500},
                     'operator': {'enum': ['equals', 'not_equals', 'contains', 'exists', 'length_equals', 'less_or_equal']},
                     'allow_error': {'type': 'boolean'},
                 }},
    },
}
Draft202012Validator.check_schema(SCHEMA)
MUTATING = {'click', 'fill', 'press', 'check', 'uncheck', 'select'}
DANGEROUS = ('delete', 'remove', 'destroy', 'drop ', 'purchase', 'pay now',
             'transfer', 'publish', 'send money', 'terminate', 'wipe', 'unsubscribe')
LOCATOR_NEEDED = {'click', 'fill', 'press', 'check', 'uncheck', 'select', 'hover', 'wait_for',
                  'assert_text', 'assert_visible', 'assert_count', 'assert_value'}
VALUE_NEEDED = {'fill', 'press', 'select'}
EXPECT_NEEDED = {'assert_text', 'assert_url', 'assert_visible', 'assert_count',
                 'assert_value', 'assert_title', 'assert_log_contains', 'assert_trace_span', 'assert_oracle'}


def validate(spec, *, local_files=False):
    Draft202012Validator(SCHEMA).validate(spec)
    origin = approved_base_url(spec['origin']) if 'origin' in spec else None
    if spec.get('driver', 'web') == 'web' and origin is None:
        raise ValueError('web driver requires origin')
    if spec.get('driver', 'web') == 'webdriver':
        if 'webdriver_url' not in spec:
            raise ValueError('webdriver requires webdriver_url')
        approved_base_url(spec['webdriver_url'])
        if spec.get('fixture_relay'):
            raise ValueError('fixture relay is only for web test fixtures')
    elif 'webdriver_url' in spec or 'capabilities' in spec:
        raise ValueError('WebDriver configuration requires driver=webdriver')
    if 'oracle_origin' in spec:
        approved_base_url(spec['oracle_origin'])
    if 'oracle_auth_env' in spec and 'oracle_origin' not in spec:
        raise ValueError('oracle auth requires oracle_origin')
    for field in ('auth_env', 'oracle_auth_env'):
        if field in spec and not os.getenv(spec[field]):
            raise ValueError(f'{field} requires configured environment secret')
    if spec.get('propagate_trace') and spec.get('driver') == 'webdriver':
        raise ValueError('WebDriver cannot inject trace headers without an instrumented proxy')
    if spec.get('fixture_relay') and not (origin and origin.startswith(('http://127.0.0.1:', 'http://localhost:'))):
        raise ValueError('fixture relay only supports local test fixtures')
    if spec.get('log_file'):
        if not local_files:
            raise ValueError('log_file requires trusted local CLI invocation')
        path = Path(spec['log_file']).resolve(strict=True)
        root = Path(os.getenv('QA_LOG_ROOT', os.getcwd())).resolve()
        if not path.is_file() or not path.is_relative_to(root):
            raise ValueError('log file must be under QA_LOG_ROOT and already exist')
    if len({step['name'] for step in spec['steps']}) != len(spec['steps']):
        raise ValueError('duplicate step name')
    if spec.get('allow_destructive') and (not spec.get('allow_mutations') or os.getenv('QA_ALLOW_DESTRUCTIVE') != '1'):
        raise ValueError('destructive UI actions need allow_mutations and QA_ALLOW_DESTRUCTIVE=1')
    for step in spec['steps']:
        action = step['action']
        if action in LOCATOR_NEEDED and 'locator' not in step:
            raise ValueError(f'{step["name"]}: locator required')
        if action in VALUE_NEEDED and 'value' not in step:
            raise ValueError(f'{step["name"]}: value required')
        if action in EXPECT_NEEDED and 'expected' not in step:
            raise ValueError(f'{step["name"]}: expected required')
        if action == 'goto' and ('path' not in step or origin is None):
            raise ValueError(f'{step["name"]}: goto requires origin and path')
        if action == 'assert_visual' and spec.get('driver', 'web') != 'web':
            raise ValueError('visual regression currently supports Playwright only')
        if action == 'audit_accessibility' and spec.get('driver', 'web') != 'web':
            raise ValueError('basic accessibility audit currently supports Playwright only')
        if action == 'assert_visual' and 'baseline' not in step:
            raise ValueError('visual assertion requires an explicitly approved baseline')
        if action in {'assert_visual', 'screenshot'} and not spec.get('screenshots'):
            raise ValueError('screenshots require explicit opt-in')
        if action == 'assert_oracle' and ('oracle_origin' not in spec or 'oracle_path' not in step or 'operator' not in step):
            raise ValueError('oracle assertion requires origin, path and operator')
        if action in MUTATING and not spec.get('allow_mutations'):
            raise ValueError('UI mutations need explicit allow_mutations=true')
        fields = [str(step.get('value', '')), step.get('locator', {}).get('value', '')]
        if action in MUTATING and any(word in ' '.join(fields).lower() for word in DANGEROUS):
            if not spec.get('allow_destructive'):
                raise ValueError('potentially destructive action needs additional approval')
        if 'baseline' in step and not local_files:
            raise ValueError('baseline path requires trusted local CLI invocation')
        if 'baseline' in step and local_files:
            root = Path(os.getenv('QA_BASELINE_ROOT', os.getcwd())).resolve()
            path = Path(step['baseline']).resolve(strict=True)
            if not path.is_file() or not path.is_relative_to(root):
                raise ValueError('baseline must exist under QA_BASELINE_ROOT')
        pointer = step.get('pointer', '')
        if pointer and (not pointer.startswith('/') or '~' in pointer.replace('~0', '').replace('~1', '')):
            raise ValueError('oracle pointer must be valid JSON Pointer')
        if action == 'assert_oracle' and step.get('operator') == 'less_or_equal' and type(step.get('expected')) not in (int, float):
            raise ValueError('less_or_equal requires numeric expected value')
    return spec
