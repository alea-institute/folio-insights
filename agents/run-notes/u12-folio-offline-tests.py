"""U12 test harness: bypass dotenv loading and reject network/credential access.

Run from the worktree root with a Python environment containing the repo deps.
Use only the explicitly selected synthetic suites documented in the run note.
This Python audit hook is a guard, not a replacement for the OS sandbox.
"""
import os,sys,socket
from pathlib import Path
root=Path.cwd()
sys.path[:0]=[str(root / 'src'),str(root)]
os.environ['PYTHONDONTWRITEBYTECODE']='1'
def audit(event,args):
    if event=='open' and isinstance(args[0],(str,bytes)):
        p=Path(os.fsdecode(args[0])); parts=p.parts; name=p.name.lower()
        if '.secrets' in parts or 'twin-secrets' in parts or name.startswith('.env') or p.suffix in ('.pem','.key') or (p.suffix not in ('.py','.pyc') and any(x in name for x in ('credential','cookie','token'))):
            raise PermissionError('U12 prohibited file read')
    if event in ('socket.connect','socket.getaddrinfo'):
        raise PermissionError('U12 network disabled')
sys.addaudithook(audit)
from pydantic_settings import BaseSettings
from pydantic_settings.sources import DotEnvSettingsSource
DotEnvSettingsSource._read_env_files=lambda self: {}
from folio_insights.config import Settings
Settings.model_config['env_file']=None
import pytest
raise SystemExit(pytest.main(sys.argv[1:]))
