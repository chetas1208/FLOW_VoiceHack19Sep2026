"""Intentionally defective tool-using agent fixture; synthetic state only."""
class FakeProjectTool:
    def __init__(self):
        self.projects = {}
        self.calls = []

    def create(self, name):
        self.calls.append(name)
        self.projects[name] = {"name": name}
        return {"created": True, "name": name}

class ProjectAgent:
    def __init__(self, tool):
        self.tool = tool

    def run(self, name):
        # KNOWN DEFECT AG-001: claims success without invoking the tool.
        return f"Project {name} created successfully"
