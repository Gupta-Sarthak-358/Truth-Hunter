import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.pool import init_pool
from models import init_db
from models.monsters import seed_monsters_and_badges


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    init_pool()
    logger.info("Initializing database before seed...")
    init_db()
    logger.info("Running monster and badge seed...")
    seed_monsters_and_badges()
    logger.info("Seed complete.")


if __name__ == "__main__":
    main()
