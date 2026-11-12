import uvicorn
from egolens.settings import load_config
from egolens.web.app import app
config=load_config()
if config['web_host'] not in ['127.0.0.1','::1','localhost']:
    raise SystemExit('The interactive research workspace must bind to loopback. Publish site/ separately.')
uvicorn.run(app,host=config['web_host'],port=config['web_port'])
