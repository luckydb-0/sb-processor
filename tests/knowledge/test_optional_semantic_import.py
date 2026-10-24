import subprocess
import sys


def test_base_cli_import_does_not_require_semantic_extra():
    code = """
import builtins
original = builtins.__import__
def blocked(name, *args, **kwargs):
    if name.startswith(('qdrant_client', 'fastembed')):
        raise ImportError('semantic extras deliberately unavailable')
    return original(name, *args, **kwargs)
builtins.__import__ = blocked
from sb_processor.cli import build_parser
assert build_parser().parse_args(['scan', '--vault', '/tmp/vault']).command == 'scan'
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
