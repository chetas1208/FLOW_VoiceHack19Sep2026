"""Ground-truth tests detect intentionally planted defects; no LLM judge required."""
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'reference_apps' / 'fullstack'))
sys.path.insert(0, str(ROOT / 'reference_apps' / 'agentic'))
from app import ORDERS, create_order
from agent import FakeProjectTool, ProjectAgent

class ReferenceOracleTests(unittest.TestCase):
    def setUp(self):
        ORDERS.clear()

    def test_fullstack_known_defect_detected(self):
        create_order('order-1', 50)
        create_order('order-1', 50)
        self.assertNotEqual(len(ORDERS['order-1']['charges']), 1, 'FS-001 must remain detectable')

    def test_fullstack_negative_control_single_call(self):
        create_order('order-2', 50)
        self.assertEqual(len(ORDERS['order-2']['charges']), 1)

    def test_agentic_known_defect_detected(self):
        tool = FakeProjectTool()
        response = ProjectAgent(tool).run('demo')
        self.assertIn('successfully', response)
        self.assertNotIn('demo', tool.projects, 'AG-001 must remain detectable')
        self.assertEqual(tool.calls, [])

    def test_agentic_negative_control_tool_works(self):
        tool = FakeProjectTool()
        result = tool.create('demo')
        self.assertTrue(result['created'])
        self.assertIn('demo', tool.projects)

if __name__ == '__main__':
    unittest.main()
