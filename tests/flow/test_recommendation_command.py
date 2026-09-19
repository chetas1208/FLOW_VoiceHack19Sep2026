from types import SimpleNamespace


def test_recommendation_command_reports_empty_state(monkeypatch, capsys):
    from services.flow.commands import recommendation

    class Empty:
        def list_sessions(self, status):
            return []

    monkeypatch.setattr(recommendation.SessionManager, "from_environment", classmethod(lambda cls: Empty()))
    assert recommendation.run(SimpleNamespace(session=None, do=False)) == 2
    assert "exactly one active" in capsys.readouterr().out
