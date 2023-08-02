

from flask import Flask
import os
from flask_cors import CORS
# from api.routes import configure_routes
from api.sockets import configure_sockets
# import api.routes
from api.routes import app_file2
app = Flask(__name__, static_url_path='',)
# CORS(app)
app.config['SECRET_KEY'] = 'secret!'

cf_port = os.getenv("PORT")

app.register_blueprint(app_file2)
    
if __name__ == '__main__':
    
    configure_sockets(app)  # Initialize sockets
    # configure_routes(app)
    if cf_port is None:
        app.run(port=3000, debug=True)

    else:
        app.run(port=int(cf_port), debug=True)