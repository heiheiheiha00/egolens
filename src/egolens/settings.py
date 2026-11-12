"""Explicit operator configuration; importing this module never loads a model."""
import json, os, pathlib

ROOT = pathlib.Path(os.getenv('EGOLENS_ROOT', pathlib.Path(__file__).resolve().parents[2])).resolve()

def _load_env():
    p=ROOT/'.env'
    if not p.exists():return
    for raw in p.read_text(encoding='utf-8-sig').splitlines():
        line=raw.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        k,v=line.split('=',1);os.environ.setdefault(k.strip(),v.strip().strip('\"\''))

_load_env()
CONFIG_PATH=pathlib.Path(os.getenv('EGOLENS_CONFIG','config.local.json'))
if not CONFIG_PATH.is_absolute():CONFIG_PATH=ROOT/CONFIG_PATH

def load_config():
    cfg=json.loads((ROOT/'config.example.json').read_text(encoding='utf-8'))
    if CONFIG_PATH.exists():cfg.update(json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig')))
    return cfg

def resolve_path(value):
    p=pathlib.Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (ROOT/p).resolve()

def executable_path(value):
    # Resolving the final python symlink bypasses pyvenv.cfg and silently runs
    # the base interpreter. Preserve the configured virtual-environment path.
    p=pathlib.Path(value).expanduser()
    return pathlib.Path(os.path.abspath(p if p.is_absolute() else ROOT/p))

def state_dir():return resolve_path(load_config()['state_dir'])

def allowed_video(path):
    p=pathlib.Path(path).resolve()
    return p.is_file() and any(p.is_relative_to(resolve_path(root)) for root in load_config()['media_roots'])

def memory_entries():
    p=resolve_path(load_config()['memory_file'])
    entries=json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    if not isinstance(entries,list):raise ValueError('memory_file must contain a JSON list')
    for item in entries:
        item['video_path']=str(resolve_path(item['video_path']))
        if not allowed_video(item['video_path']):raise ValueError('Memory source is missing or outside configured media_roots')
    return entries
