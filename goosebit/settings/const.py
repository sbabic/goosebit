import secrets
from pathlib import Path

from argon2 import PasswordHasher
from joserfc.jwk import OctKey

BASE_DIR = Path(__file__).resolve().parent.parent
DB_MIGRATIONS_LOC = BASE_DIR.joinpath("migrations")

SECRET = OctKey.import_key(secrets.token_hex(16))
PWD_CXT = PasswordHasher()

LOGGING_DEFAULT = {
    "version": 1,
    "formatters": {"simple": {"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple", "level": "DEBUG"}},
    "loggers": {
        "tortoise": {"handlers": ["console"], "level": "WARNING", "propagate": True},
        "aiosqlite": {"handlers": ["console"], "level": "WARNING", "propagate": True},
        "multipart": {"handlers": ["console"], "level": "INFO", "propagate": True},
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}