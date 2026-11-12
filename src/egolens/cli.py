"""Minimal public command line; experiment runners intentionally excluded."""
import argparse

def main():
    p=argparse.ArgumentParser(prog='egolens');sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor',help='Check configuration without loading GPU models')
    for action in ['start','stop','status']:
        q=sub.add_parser(action);q.add_argument('--services',nargs='+',choices=['visual','tracker','web'],default=['tracker','visual','web'] if action!='stop' else ['web','visual','tracker'])
    q=sub.add_parser('site',help='Serve only the project page, without GPU/API calls');q.add_argument('--host',default='127.0.0.1');q.add_argument('--port',type=int,default=18781)
    q=sub.add_parser('ingest',help='Index a private video using the running visual service');q.add_argument('video');q.add_argument('--day',default='DAY1');q.add_argument('--start',default='12000000');q.add_argument('--title');q.add_argument('--segment-seconds',type=float,default=30);q.add_argument('--transcribe',action='store_true')
    q=sub.add_parser('transcribe',help='Prepare VAD/ASR with operator-provided weights');q.add_argument('video');q.add_argument('--start',default='12000000')
    a=p.parse_args()
    if a.command in ['start','stop','status']:
        from egolens.control import control
        control(a.command,a.services)
    elif a.command=='doctor':
        from egolens.control import doctor
        raise SystemExit(0 if doctor() else 1)
    elif a.command=='site':
        from egolens.site_server import serve
        serve(a.host,a.port)
    elif a.command=='ingest':
        from egolens.ingest import ingest
        ingest(a)
    elif a.command=='transcribe':
        from egolens.audio.transcribe import transcribe
        transcribe(a.video,a.start)
