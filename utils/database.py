# utils/database.py
from pymongo import MongoClient
import os

class DB:
    def __init__(self, uri: str):
        self.client = MongoClient(uri)
        self.db = self.client.get_default_database()

    def add_user(self, user_id: int):
        self.db.users.update_one({"_id": user_id}, {"$setOnInsert": {"_id": user_id}}, upsert=True)

    def log_task(self, user_id: int, url: str, filename: str, size: int | None):
        self.db.tasks.insert_one({"user_id": user_id, "url": url, "filename": filename, "size": size})
