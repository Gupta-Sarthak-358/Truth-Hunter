from dotenv import load_dotenv
load_dotenv()
import db.pool
import psycopg2

db.pool.init_pool()
conn = db.pool.db_pool.getconn()
conn.autocommit = True
cur = conn.cursor()
alters = [
    "ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE everyday_tasks ADD COLUMN recurrence TEXT DEFAULT 'daily'",
    "ALTER TABLE everyday_tasks ADD COLUMN sort_order INTEGER DEFAULT 0",
    "ALTER TABLE task_instances ADD COLUMN sort_order INTEGER DEFAULT 0",
    "ALTER TABLE meta ADD COLUMN user_id INTEGER",
    "ALTER TABLE monsters ADD COLUMN flavor_text TEXT",
    "ALTER TABLE gamification_stats ADD COLUMN perfect_days INTEGER DEFAULT 0",
    "ALTER TABLE gamification_stats ADD COLUMN type_complete_count INTEGER DEFAULT 0",
    "ALTER TABLE gamification_stats ADD COLUMN xp INTEGER DEFAULT 0",
    "ALTER TABLE gamification_stats ADD COLUMN level INTEGER DEFAULT 1",
    "ALTER TABLE gamification_stats ADD COLUMN freeze_charges INTEGER DEFAULT 0",
    "ALTER TABLE gamification_stats ADD COLUMN freeze_used_date TEXT",
    "ALTER TABLE gamification_stats ADD COLUMN last_perfect_day TEXT",
    "ALTER TABLE gamification_stats ADD COLUMN last_freeze_award TEXT"
]

for q in alters:
    try:
        cur.execute(q)
        print("Success:", q)
    except psycopg2.Error as e:
        pass
