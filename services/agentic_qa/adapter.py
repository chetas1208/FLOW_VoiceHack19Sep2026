"""An explicit Python agent adapter; verifies external state, not self-report."""
from reference_apps.agentic.agent import FakeProjectTool, ProjectAgent

def verify_project_creation(name='demo'):
    tool = FakeProjectTool()
    answer = ProjectAgent(tool).run(name)
    actual = name in tool.projects
    return {'verdict':'PASS' if actual else 'FAIL', 'assertions':{'project_exists':actual}, 'observed':{'agent_response':answer,'projects':tool.projects,'tool_calls':tool.calls}}
