from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os

env = os.environ.get("FLASK_ENV", "development")

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://" if env == "development" else None,
)
