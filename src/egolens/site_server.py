"""CPU-only project-page preview. The inference entry explicitly remains offline."""
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from egolens.settings import ROOT
class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'site'),**kw)
def serve(host,port):
    print(f'Project page only: http://{host}:{port}/ ; GPU models remain off',flush=True);ThreadingHTTPServer((host,port),Handler).serve_forever()
