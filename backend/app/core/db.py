"""MongoDB access. Synchronous PyMongo throughout; FastAPI runs sync handlers in a thread pool."""
from __future__ import annotations

from functools import lru_cache

import gridfs
from pymongo import MongoClient
from pymongo.database import Database

from app.core.config import get_settings


@lru_cache
def get_client() -> MongoClient:
    return MongoClient(get_settings().mongodb_uri, serverSelectionTimeoutMS=8000, tz_aware=True, appname="greenlight-backend")


def get_db() -> Database:
    return get_client()[get_settings().mongodb_db]


def bucket() -> gridfs.GridFSBucket:
    """Audio and image files live in GridFS in the same database, so every laptop sees the same files."""
    return gridfs.GridFSBucket(get_db())


def oid(value):
    """Accept a string or an ObjectId. Seeded and test data may use plain string ids."""
    from bson import ObjectId
    from bson.errors import InvalidId

    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return value
