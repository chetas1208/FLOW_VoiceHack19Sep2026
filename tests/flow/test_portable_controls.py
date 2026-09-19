from __future__ import annotations

from types import SimpleNamespace


def test_voice_controls_persist_enabled_and_mute_state(tmp_path, monkeypatch, capsys):
    from services.flow.commands import voice

    monkeypatch.setattr(voice, "config_dir", lambda: tmp_path)
    assert voice.run(SimpleNamespace(action="on", minutes=30)) == 0
    assert voice.run(SimpleNamespace(action="mute", minutes=5)) == 0
    assert voice.run(SimpleNamespace(action="status", minutes=30)) == 0
    output = capsys.readouterr().out
    assert "enabled" in output
    assert "Muted until:" in output


def test_voice_mute_rejects_non_positive_duration(tmp_path, monkeypatch, capsys):
    from services.flow.commands import voice

    monkeypatch.setattr(voice, "config_dir", lambda: tmp_path)
    assert voice.run(SimpleNamespace(action="mute", minutes=0)) == 2
    assert "at least 1" in capsys.readouterr().out
