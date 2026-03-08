from pymongo import pymongo

class Productos(pymongo.Document):
    name = pymongo.StringField(required=True)
    email = pymongo.StringField(required=True)