

from flask import Flask
import os
from flask_cors import CORS
from dotenv import load_dotenv
# from api.routes import configure_routes
from api.sockets import configure_sockets
# import api.routes
from api.routes import app_file2
from pymongo import MongoClient

# Load environment variables
load_dotenv()

app = Flask(__name__, static_url_path='',)
CORS(app)
app.config['SECRET_KEY'] = 'secret!'

cf_port = os.getenv("PORT")

app.register_blueprint(app_file2)
    
if __name__ == '__main__':
    
    configure_sockets(app)  # Initialize sockets
    # configure_routes(app)
    if cf_port is None:
        
        # MongoDB connection
        mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        app.mongodb_client = MongoClient(mongodb_uri)
        app.database = app.mongodb_client["lalistita"]
        print("Connected to the MongoDB database!")

        app.run(port=3000, debug=True)

    else:
        # Production environment
        mongodb_uri = os.getenv("MONGODB_URI")
        if mongodb_uri:
            app.mongodb_client = MongoClient(mongodb_uri)
            app.database = app.mongodb_client["lalistita"]
            print("Connected to the MongoDB database!")
        
        app.run(port=int(cf_port), debug=True)