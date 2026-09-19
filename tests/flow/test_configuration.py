from types import SimpleNamespace


def test_privacy_configuration_persists_exclusions(tmp_path, monkeypatch, capsys):
    from services.flow.commands import configuration

    monkeypatch.setattr(configuration, "config_dir", lambda: tmp_path)
    assert configuration.run(SimpleNamespace(action="exclude-app", application="Private Notes")) == 0
    assert configuration.run(SimpleNamespace(action="list", application=None)) == 0
    assert "private notes" in capsys.readouterr().out
    assert configuration.run(SimpleNamespace(action="include-app", application="Private Notes")) == 0
    assert "private notes" not in configuration.PrivacyPolicy.load(tmp_path / "privacy.json").excluded_apps
