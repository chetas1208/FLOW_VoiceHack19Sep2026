# Packaging and installation

The repository is installable with `pip install .` or `pip install -e .` and
exposes `flow` through `[project.scripts]`. `flow-agent[voice]` is optional and
loads Kokoro lazily; the base package does not download model weights.

The development installer is `scripts/install.sh`. It prefers `pipx`, otherwise
uses `~/.local/share/flow/venv` and links `~/.local/bin/flow`. It does not edit
shell startup files or require sudo. Review it before using any curl-piped
install command.
