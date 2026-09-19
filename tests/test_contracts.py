import json
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / 'contracts' / 'schemas'
class ContractTests(unittest.TestCase):
    def test_all_schemas_have_version_and_strict_top_level(self):
        files = list(SCHEMAS.glob('*.schema.json'))
        self.assertGreaterEqual(len(files), 10)
        for file in files:
            with self.subTest(schema=file.name):
                data = json.loads(file.read_text())
                self.assertEqual(data['properties']['schema_version']['const'], '1.0')
                self.assertFalse(data['additionalProperties'])
                self.assertIn('schema_version', data['required'])

    def test_schema_draft_validation_if_available(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest('pip install -r requirements-dev.txt for JSON Schema meta-validation')
        for file in SCHEMAS.glob('*.schema.json'):
            with self.subTest(schema=file.name):
                Draft202012Validator.check_schema(json.loads(file.read_text()))
if __name__ == '__main__': unittest.main()
