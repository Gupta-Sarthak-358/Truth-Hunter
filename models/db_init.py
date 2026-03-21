from db import get_cursor


def init_db():
    with get_cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            password_changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        )

        cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            color TEXT DEFAULT '#4a90d9',
            monster_type_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS everyday_tasks (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            category_id INTEGER,
            recurrence TEXT DEFAULT 'daily',
            sort_order INTEGER DEFAULT 0
        )
        """)
        cur.execute(
            "ALTER TABLE everyday_tasks ADD COLUMN IF NOT EXISTS recurrence TEXT DEFAULT 'daily'"
        )
        cur.execute(
            "ALTER TABLE everyday_tasks ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0"
        )

        cur.execute("""
        CREATE TABLE IF NOT EXISTS task_instances (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            everyday_task_id INTEGER,
            is_completed INTEGER DEFAULT 0,
            is_locked INTEGER DEFAULT 0,
            is_voided INTEGER DEFAULT 0,
            weight INTEGER NOT NULL,
            category_id INTEGER,
            notes TEXT,
            due_date TEXT,
            priority INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            UNIQUE(name, date, user_id)
        )
        """)
        cur.execute(
            "ALTER TABLE task_instances ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0"
        )

        cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            user_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (user_id, key)
        )
        """)
        cur.execute("ALTER TABLE meta ADD COLUMN IF NOT EXISTS user_id INTEGER")
        cur.execute(
            """
            UPDATE meta
            SET user_id = NULLIF(substring(key from length('last_processed_') + 1 for 10), '')::INTEGER
            WHERE user_id IS NULL AND key LIKE 'last_processed_%'
            """
        )
        cur.execute(
            """
            UPDATE meta
            SET user_id = 0
            WHERE user_id IS NULL
            """
        )
        cur.execute("DROP INDEX IF EXISTS meta_key_idx")
        cur.execute(
            """
            DO $$
            DECLARE
                meta_key_pk boolean;
            BEGIN
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
                    WHERE t.relname = 'meta'
                      AND c.conname = 'meta_pkey'
                    GROUP BY c.oid
                    HAVING COUNT(*) = 1 AND MIN(a.attname) = 'key'
                )
                INTO meta_key_pk;

                IF meta_key_pk THEN
                    ALTER TABLE meta DROP CONSTRAINT meta_pkey;
                END IF;
            END
            $$;
            """
        )
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'meta'
                      AND column_name = 'user_id'
                      AND is_nullable = 'NO'
                ) AND NOT EXISTS (SELECT 1 FROM meta WHERE user_id IS NULL) THEN
                    ALTER TABLE meta ALTER COLUMN user_id SET NOT NULL;
                END IF;
            END
            $$;
            """
        )
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'meta_pkey'
                ) THEN
                    ALTER TABLE meta ADD CONSTRAINT meta_pkey PRIMARY KEY (user_id, key);
                END IF;
            END
            $$;
            """
        )

        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_instances_date ON task_instances(date)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_instances_user_date ON task_instances(user_id, date)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_instances_user_date_weight ON task_instances(user_id, date, weight)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_instances_user_date_voided ON task_instances(user_id, date, is_voided)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_everyday_user_active ON everyday_tasks(user_id, active)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_everyday_user_active_sort ON everyday_tasks(user_id, active, sort_order)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_categories_user_id ON categories(user_id)"
        )

        cur.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            ip_address TEXT NOT NULL,
            username TEXT NOT NULL,
            attempts INTEGER DEFAULT 1,
            locked_until TIMESTAMP,
            PRIMARY KEY (ip_address, username)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS monster_types (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            icon TEXT,
            color TEXT DEFAULT '#888888',
            category_id INTEGER
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS monsters (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            type_id INTEGER NOT NULL,
            rarity TEXT DEFAULT 'common',
            image_emoji TEXT,
            shiny_emoji TEXT,
            flavor_text TEXT
        )
        """)
        cur.execute("ALTER TABLE monsters ADD COLUMN IF NOT EXISTS flavor_text TEXT")

        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_monsters (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            monster_id INTEGER NOT NULL,
            task_instance_id INTEGER,
            caught_date TEXT NOT NULL,
            is_shiny INTEGER DEFAULT 0
        )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_monsters_user ON user_monsters(user_id)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_monsters_user_caught_date ON user_monsters(user_id, caught_date DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_monsters_user_task ON user_monsters(user_id, task_instance_id)"
        )

        cur.execute("""
        CREATE TABLE IF NOT EXISTS badges (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            icon_emoji TEXT,
            condition_type TEXT,
            condition_value INTEGER
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_badges (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            badge_id INTEGER NOT NULL,
            earned_date TEXT NOT NULL,
            UNIQUE(user_id, badge_id)
        )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_badges_user_id ON user_badges(user_id)"
        )

        cur.execute("""
        CREATE TABLE IF NOT EXISTS gamification_stats (
            user_id INTEGER PRIMARY KEY,
            total_tasks_completed INTEGER DEFAULT 0,
            current_streak INTEGER DEFAULT 0,
            longest_streak INTEGER DEFAULT 0,
            last_completion_date TEXT,
            perfect_days INTEGER DEFAULT 0,
            type_complete_count INTEGER DEFAULT 0,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            freeze_charges INTEGER DEFAULT 0,
            freeze_used_date TEXT,
            last_perfect_day TEXT,
            last_freeze_award TEXT
        )
        """)
        cur.execute(
            "ALTER TABLE gamification_stats ADD COLUMN IF NOT EXISTS perfect_days INTEGER DEFAULT 0"
        )
        cur.execute(
            "ALTER TABLE gamification_stats ADD COLUMN IF NOT EXISTS type_complete_count INTEGER DEFAULT 0"
        )
        cur.execute(
            "ALTER TABLE gamification_stats ADD COLUMN IF NOT EXISTS xp INTEGER DEFAULT 0"
        )
        cur.execute(
            "ALTER TABLE gamification_stats ADD COLUMN IF NOT EXISTS level INTEGER DEFAULT 1"
        )
        cur.execute(
            "ALTER TABLE gamification_stats ADD COLUMN IF NOT EXISTS freeze_charges INTEGER DEFAULT 0"
        )
        cur.execute(
            "ALTER TABLE gamification_stats ADD COLUMN IF NOT EXISTS freeze_used_date TEXT"
        )
        cur.execute(
            "ALTER TABLE gamification_stats ADD COLUMN IF NOT EXISTS last_perfect_day TEXT"
        )
        cur.execute(
            "ALTER TABLE gamification_stats ADD COLUMN IF NOT EXISTS last_freeze_award TEXT"
        )
