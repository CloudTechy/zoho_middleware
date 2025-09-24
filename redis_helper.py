# redis.py

import redis
import os
from dotenv import load_dotenv
import json
import logging

# Load environment variables from .env
load_dotenv()

# Redis config for ERP/middleware instance
REDIS_HOST = os.getenv("REDIS_ERP_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_ERP_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_ERP_DB", 3))
REDIS_NAMESPACE = os.getenv("REDIS_ERP_NAMESPACE", "zoho_odoo_middleware")

# Redis client
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)


# Set up basic logging
logging.basicConfig(level=logging.INFO)

def _ns_key(key: str) -> str:
    """Applies namespace to key."""
    namespaced_key = f"{REDIS_NAMESPACE}:{key}"
    logging.debug(f"Returning Namespaced key: {namespaced_key}")
    return namespaced_key

def redis_set(key: str, value, ex=None):
    """
    Set key with JSON-encoded value and optional expiry.
    ex = expiration in seconds
    """
    namespaced_key = _ns_key(key)
    logging.info(f"Setting Redis key: {namespaced_key}, value: {value}, ex: {ex}")
    try:
        redis_client.set(namespaced_key, json.dumps(value), ex=ex)
    except Exception as e:
        logging.error(f"Error setting key {namespaced_key}: {e}")

def redis_get(key: str):
    """Get key and decode JSON."""
    namespaced_key = _ns_key(key)
    try:
        val = redis_client.get(namespaced_key)
        if val:
            logging.info(f"Retrieved Redis key: {namespaced_key}, value: {val}")
            return json.loads(val)
        else:
            logging.warning(f"Key not found or expired: {namespaced_key}")
            return None
    except Exception as e:
        logging.error(f"Error getting key {namespaced_key}: {e}")
        return None

def redis_delete(key: str):
    """Delete key from Redis."""
    namespaced_key = _ns_key(key)
    try:
        redis_client.delete(namespaced_key)
        logging.info(f"Deleted Redis key: {namespaced_key}")
    except Exception as e:
        logging.error(f"Error deleting key {namespaced_key}: {e}")

def redis_key_exists(key: str) -> bool:
    """Check if a key exists in Redis."""
    namespaced_key = _ns_key(key)
    exists = redis_client.exists(namespaced_key)
    logging.info(f"Key exists: {namespaced_key} -> {exists}")
    return exists

def list_all_keys():
    """List all keys in the current Redis DB."""
    try:
        keys = redis_client.keys(f"{REDIS_NAMESPACE}:*")
        return [key.decode('utf-8') for key in keys]
    except Exception as e:
        logging.error(f"Error listing keys: {e}")
        return []