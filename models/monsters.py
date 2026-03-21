from datetime import timedelta
from db import get_cursor
from utils import utc_today, format_date_iso, get_cached
from constants import RARITY_CHANCE, SHINY_THRESHOLDS, MONSTERS_PER_PAGE
import random

PLACEHOLDER = "%s"


def get_monster_types():
    with get_cursor() as cur:
        cur.execute("SELECT * FROM monster_types ORDER BY name")
        types = cur.fetchall()
    return [dict(row) for row in types]


def _load_monster_catalog():
    with get_cursor() as cur:
        cur.execute("SELECT id, type_id, rarity FROM monsters")
        rows = cur.fetchall()

    by_type_and_rarity = {}
    by_type = {}
    all_ids = []

    for row in rows:
        monster_id = row["id"]
        type_id = row["type_id"]
        rarity = row["rarity"]
        by_type_and_rarity.setdefault((type_id, rarity), []).append(monster_id)
        by_type.setdefault(type_id, []).append(monster_id)
        all_ids.append(monster_id)

    return {
        "by_type_and_rarity": by_type_and_rarity,
        "by_type": by_type,
        "all": all_ids,
    }


def _get_monster_catalog():
    return get_cached("shared:monster_catalog", _load_monster_catalog, ttl=300)


def _load_category_type_map(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, monster_type_id
            FROM categories
            WHERE user_id = {PLACEHOLDER}
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    return {
        row["id"]: row["monster_type_id"]
        for row in rows
        if row.get("monster_type_id") is not None
    }


def _choose_monster_id(catalog, type_id, rarity):
    candidates = catalog["by_type_and_rarity"].get((type_id, rarity))
    if candidates:
        return random.choice(candidates)

    type_candidates = catalog["by_type"].get(type_id)
    if type_candidates:
        return random.choice(type_candidates)

    all_candidates = catalog["all"]
    if all_candidates:
        return random.choice(all_candidates)

    return None


def get_user_monsters(user_id, type_id=None, page=1, per_page=MONSTERS_PER_PAGE):
    offset = (page - 1) * per_page
    with get_cursor() as cur:
        count_query = f"""
            SELECT COUNT(*) as total FROM user_monsters um
            JOIN monsters m ON um.monster_id = m.id
            WHERE um.user_id = {PLACEHOLDER}
        """
        if type_id:
            count_query += f" AND m.type_id = {PLACEHOLDER}"
            count_params = (user_id, type_id)
        else:
            count_params = (user_id,)

        cur.execute(count_query, count_params)
        total_row = cur.fetchone()
        total = total_row["total"] if total_row else 0

        base_query = f"""
            SELECT um.*, m.name, m.image_emoji, m.shiny_emoji, m.rarity, m.flavor_text,
                   mt.name as type_name, mt.color as type_color, mt.icon as type_icon,
                   t.name as task_name
            FROM user_monsters um
            JOIN monsters m ON um.monster_id = m.id
            JOIN monster_types mt ON m.type_id = mt.id
            LEFT JOIN task_instances t ON um.task_instance_id = t.id
            WHERE um.user_id = {PLACEHOLDER}
        """
        if type_id:
            base_query += f" AND m.type_id = {PLACEHOLDER}"

        base_query += f" ORDER BY um.caught_date DESC LIMIT {per_page} OFFSET {offset}"

        if type_id:
            query_params = (user_id, type_id)
        else:
            query_params = (user_id,)

        cur.execute(base_query, query_params)
        monsters = cur.fetchall()

    return [dict(row) for row in monsters], total


def get_recent_monsters(user_id, limit=3):
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT um.*, m.name, m.image_emoji, m.shiny_emoji, m.rarity, m.flavor_text,
                   mt.name as type_name, mt.color as type_color, mt.icon as type_icon,
                   t.name as task_name
            FROM user_monsters um
            JOIN monsters m ON um.monster_id = m.id
            JOIN monster_types mt ON m.type_id = mt.id
            LEFT JOIN task_instances t ON um.task_instance_id = t.id
            WHERE um.user_id = {PLACEHOLDER}
            ORDER BY um.caught_date DESC
            LIMIT {limit}
        """,
            (user_id,),
        )
        monsters = cur.fetchall()
    return [dict(row) for row in monsters]


def get_uncaught_monsters(user_id, type_id=None):
    with get_cursor() as cur:
        query = f"""
            SELECT m.*, mt.name as type_name, mt.color as type_color, mt.icon as type_icon
            FROM monsters m
            JOIN monster_types mt ON m.type_id = mt.id
            WHERE m.id NOT IN (
                SELECT DISTINCT monster_id
                FROM user_monsters
                WHERE user_id = {PLACEHOLDER}
            )
        """
        params = [user_id]

        if type_id:
            query += f" AND m.type_id = {PLACEHOLDER}"
            params.append(type_id)

        query += " ORDER BY mt.name, CASE m.rarity WHEN 'legendary' THEN 3 WHEN 'rare' THEN 2 ELSE 1 END, m.name"

        cur.execute(query, tuple(params))
        rows = cur.fetchall()

    return [dict(row) for row in rows]


def award_monster(user_id, task_instance_id, category_id=None):
    category_type_map = get_cached(
        f"user:{user_id}:category_type_map",
        lambda: _load_category_type_map(user_id),
        ttl=60,
    )
    catalog = _get_monster_catalog()

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
                EXISTS(
                    SELECT 1
                    FROM user_monsters
                    WHERE user_id = {PLACEHOLDER}
                      AND task_instance_id = {PLACEHOLDER}
                ) AS already_awarded,
                (
                    SELECT COUNT(*)
                    FROM task_instances
                    WHERE user_id = {PLACEHOLDER}
                      AND is_completed = 1
                      AND date >= {PLACEHOLDER}
                      AND date <= {PLACEHOLDER}
                ) AS completion_count
            """,
            (
                user_id,
                task_instance_id,
                user_id,
                format_date_iso(utc_today() - timedelta(days=7)),
                format_date_iso(utc_today()),
            ),
        )
        status_row = cur.fetchone()
        if status_row and status_row["already_awarded"]:
            return None, False, False, 0, 0

        available_types = list(catalog["by_type"].keys())
        if not available_types:
            return None, False, False, 0, 0

        type_id = category_type_map.get(category_id) if category_id else None
        if type_id is None:
            type_id = random.choice(available_types)

        today_str = format_date_iso(utc_today())
        completion_count = status_row["completion_count"] if status_row else 0

        shiny_chance = 0
        for threshold, chance in sorted(SHINY_THRESHOLDS.items()):
            if completion_count >= threshold:
                shiny_chance = int(chance * 100)

        is_shiny = 1 if random.randint(1, 100) <= shiny_chance else 0

        rarity_roll = random.randint(1, 100)
        if rarity_roll <= int(RARITY_CHANCE["legendary"] * 100):
            rarity = "legendary"
        elif rarity_roll <= int(
            (RARITY_CHANCE["legendary"] + RARITY_CHANCE["rare"]) * 100
        ):
            rarity = "rare"
        else:
            rarity = "common"

        monster_id = _choose_monster_id(catalog, type_id, rarity)
        if monster_id is None:
            return None, False, False, 0, 0

        cur.execute(
            f"""
            INSERT INTO user_monsters (user_id, monster_id, task_instance_id, caught_date, is_shiny)
            VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
        """,
            (user_id, monster_id, task_instance_id, today_str, is_shiny),
        )

        return monster_id, is_shiny, False, 1, 0


def has_migrated_monsters(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"SELECT value FROM meta WHERE user_id = {PLACEHOLDER} AND key = {PLACEHOLDER}",
            (user_id, "migrated_monsters"),
        )
        row = cur.fetchone()
        return row is not None


def export_collection(user_id):
    with get_cursor() as cur:
        cur.execute(
            f"SELECT * FROM user_monsters WHERE user_id = {PLACEHOLDER}", (user_id,)
        )
        monsters = [dict(row) for row in cur.fetchall()]

        cur.execute(
            f"""
            SELECT b.*, ub.earned_date FROM user_badges ub
            JOIN badges b ON ub.badge_id = b.id
            WHERE ub.user_id = {PLACEHOLDER}
        """,
            (user_id,),
        )
        badges = [dict(row) for row in cur.fetchall()]

        cur.execute(
            f"SELECT * FROM gamification_stats WHERE user_id = {PLACEHOLDER}",
            (user_id,),
        )
        stats_row = cur.fetchone()
        stats = dict(stats_row) if stats_row else None

    from datetime import datetime, timezone

    return {
        "version": 1,
        "export_date": datetime.now(timezone.utc).isoformat(),
        "monsters": monsters,
        "badges": badges,
        "stats": stats,
    }


def import_collection(user_id, data):
    if data.get("version") != 1:
        return False

    with get_cursor() as cur:
        for m in data.get("monsters", []):
            cur.execute(
                f"""
                INSERT INTO user_monsters (user_id, monster_id, task_instance_id, caught_date, is_shiny)
                VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
            """,
                (
                    user_id,
                    m["monster_id"],
                    m.get("task_instance_id"),
                    m["caught_date"],
                    m["is_shiny"],
                ),
            )

        for b in data.get("badges", []):
            cur.execute(
                f"""
                INSERT INTO user_badges (user_id, badge_id, earned_date)
                VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})
                ON CONFLICT (user_id, badge_id) DO NOTHING
            """,
                (user_id, b["badge_id"], b["earned_date"]),
            )
    return True


def seed_monsters_and_badges():
    import logging

    logger = logging.getLogger(__name__)

    monster_types_data = [
        ("Crawler", "????", "#A6B91A", None),
        ("Verdant", "????", "#27AE60", None),
        ("Tidal", "????", "#3498DB", None),
        ("Radiant", "????", "#E74C3C", None),
        ("Spark", "???", "#F1C40F", None),
        ("Glacial", "??????", "#74B9FF", None),
        ("Ferrous", "??????", "#95A5A6", None),
        ("Cerebral", "????", "#9B59B6", None),
        ("Combat", "??????", "#8B4513", None),
        ("Aerial", "???????", "#DDA0DD", None),
    ]
    monsters_data = [
        ("Crawleon", 1, "common", "????", "????"),
        ("Bugling", 1, "common", "????", "????"),
        ("Leafant", 1, "rare", "????", "????"),
        ("Thornix", 1, "rare", "????", "??????"),
        ("Snapper", 1, "legendary", "????", "????"),
        ("Webweaver", 1, "common", "???????", "???????"),
        ("Florox", 2, "common", "????", "????"),
        ("Grassling", 2, "common", "????", "??????"),
        ("Bloomling", 2, "rare", "????", "???????"),
        ("Rootox", 2, "rare", "????", "????"),
        ("Petalix", 2, "legendary", "????", "????"),
        ("Vinecurl", 2, "common", "????", "????"),
        ("Aquafish", 3, "common", "????", "????"),
        ("Wavepup", 3, "common", "????", "????"),
        ("Swirlix", 3, "rare", "????", "????"),
        ("Coralox", 3, "rare", "????", "????"),
        ("Depthray", 3, "legendary", "????", "???"),
        ("Tidalfin", 3, "common", "????", "????"),
        ("Emberkit", 4, "common", "????", "????"),
        ("Flamefang", 4, "common", "????", "????"),
        ("Sunpup", 4, "rare", "??????", "????"),
        ("Blazeling", 4, "rare", "????", "????"),
        ("Inferfox", 4, "legendary", "????", "????"),
        ("Sparklet", 4, "common", "???????", "????"),
        ("Volthop", 5, "common", "???", "????"),
        ("Zaprat", 5, "common", "????", "????"),
        ("Thunderbug", 5, "rare", "????", "????"),
        ("Sparkleon", 5, "rare", "????", "????"),
        ("Boltiger", 5, "legendary", "????", "???"),
        ("Chargepup", 5, "common", "????", "????"),
        ("Frostling", 6, "common", "??????", "???????"),
        ("Icetail", 6, "common", "????", "????"),
        ("Chillpup", 6, "rare", "????", "???????"),
        ("Snowfang", 6, "rare", "????", "???"),
        ("Blizzard", 6, "legendary", "????", "????"),
        ("Cryopup", 6, "common", "????", "????"),
        ("Metalwing", 7, "common", "???????", "???????"),
        ("Ironclaw", 7, "common", "????", "????"),
        ("Steelite", 7, "rare", "??????", "????"),
        ("Gearbox", 7, "rare", "??????", "???????"),
        ("Forgebug", 7, "legendary", "????", "????"),
        ("Bolthead", 7, "common", "????", "????"),
        ("Mindbug", 8, "common", "????", "????"),
        ("Psychling", 8, "common", "????", "????"),
        ("Brainfly", 8, "rare", "????", "????"),
        ("Thoughtox", 8, "rare", "????", "????"),
        ("Dreamweaver", 8, "legendary", "????", "????"),
        ("Wisppup", 8, "common", "????", "????"),
        ("Strikeleon", 9, "common", "????", "????"),
        ("Brawlrat", 9, "common", "????", "???????"),
        ("Fistling", 9, "rare", "????", "???"),
        ("Blockox", 9, "rare", "???????", "????"),
        ("Warchampion", 9, "legendary", "??????", "????"),
        ("Kickscoot", 9, "common", "????", "????"),
        ("Windrix", 10, "common", "????", "???????"),
        ("Gustbug", 10, "common", "????", "????"),
        ("Feathersnap", 10, "rare", "????", "????"),
        ("Skyhopper", 10, "rare", "????", "??????"),
        ("Cloudpup", 10, "common", "??????", "???????"),
        ("Stormwing", 10, "legendary", "????", "???"),
    ]
    badges_data = [
        ("Initiate", "Complete your first task", "????", "tasks_total", 1),
        ("Apprentice", "Complete 10 tasks", "????", "tasks_total", 10),
        ("Adept", "Complete 50 tasks", "???", "tasks_total", 50),
        ("Master", "Complete 100 tasks", "????", "tasks_total", 100),
        ("Grandmaster", "Complete 500 tasks", "????", "tasks_total", 500),
        ("Week Warden", "7-day streak", "????", "streak", 7),
        ("Month Master", "30-day streak", "???????", "streak", 30),
        ("Century Champion", "100-day streak", "???????", "streak", 100),
        ("Perfect Day", "Complete all tasks in a day", "????", "perfect_days", 1),
        ("Flawless Week", "7 perfect days", "????", "perfect_days", 7),
        ("Type Specialist", "Collect all monsters of one type", "????", "type_complete", 1),
        ("Monster Hunter", "Collect 25 unique monsters", "????", "unique_monsters", 25),
        ("Legendary Hunter", "Catch a legendary monster", "????", "legendary_caught", 1),
        ("Shiny Seeker", "Catch your first shiny", "???", "shiny_caught", 1),
        ("Collector", "Collect 50 unique monsters", "????", "unique_monsters", 50),
    ]

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) as cnt FROM monster_types")
        types_row = cur.fetchone()
        types_count = types_row["cnt"] if types_row else 0
        if types_count == 0:
            cur.executemany(
                f"INSERT INTO monster_types (name, icon, color, category_id) VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})",
                monster_types_data,
            )
            logger.info("Seeded monster types", extra={"metric": "seed_monster_types", "metric_value": len(monster_types_data)})
        else:
            logger.info("Monster types already seeded. Skipping.")

        cur.execute("SELECT COUNT(*) as cnt FROM monsters")
        monsters_row = cur.fetchone()
        monsters_count = monsters_row["cnt"] if monsters_row else 0
        if monsters_count == 0:
            cur.executemany(
                f"INSERT INTO monsters (name, type_id, rarity, image_emoji, shiny_emoji, flavor_text) VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})",
                [(name, type_id, rarity, image_emoji, shiny_emoji, None) for name, type_id, rarity, image_emoji, shiny_emoji in monsters_data],
            )
            logger.info("Seeded monsters", extra={"metric": "seed_monsters", "metric_value": len(monsters_data)})
        else:
            logger.info("Monsters already seeded. Skipping.")

        _ensure_monster_flavor_text(cur)

        cur.execute("SELECT COUNT(*) as cnt FROM badges")
        badges_row = cur.fetchone()
        badges_count = badges_row["cnt"] if badges_row else 0
        if badges_count == 0:
            cur.executemany(
                f"INSERT INTO badges (name, description, icon_emoji, condition_type, condition_value) VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER})",
                badges_data,
            )
            logger.info("Seeded badges", extra={"metric": "seed_badges", "metric_value": len(badges_data)})
        else:
            logger.info("Badges already seeded. Skipping.")


def _ensure_monster_flavor_text(cur):
    cur.execute("SELECT COUNT(*) as cnt FROM monsters WHERE flavor_text IS NULL OR flavor_text = ''")
    missing_row = cur.fetchone()
    if not missing_row or missing_row["cnt"] == 0:
        return

    flavor_updates = [
        ("Crawleon", "Feeds on unfinished tasks and half-made plans."),
        ("Bugling", "Chirps louder whenever your focus starts to slip."),
        ("Leafant", "Builds tiny nests beside habits that keep growing."),
        ("Thornix", "Defends disciplined routines with sharp, stubborn patience."),
        ("Snapper", "Appears only when a chaotic week is finally brought to heel."),
        ("Webweaver", "Spins invisible traps for procrastination and excuses."),
        ("Florox", "Blooms quietly whenever consistency is treated with care."),
        ("Grassling", "A shy sprout that follows the first signs of momentum."),
        ("Bloomling", "Unfolds only after several days of patient progress."),
        ("Rootox", "Its roots deepen every time you return to the work."),
        ("Petalix", "Said to flower only for those who finish what they begin."),
        ("Vinecurl", "Wraps itself around habits strong enough to survive bad days."),
        ("Aquafish", "Swims faster the moment your attention finally settles."),
        ("Wavepup", "Plays in the current of a smooth, uninterrupted session."),
        ("Swirlix", "Thrives in deep stretches of concentration and silence."),
        ("Coralox", "Builds bright reefs from repeated wins no one else notices."),
        ("Depthray", "Rises from the deep only when discipline becomes instinct."),
        ("Tidalfin", "Leaves gentle ripples behind every completed task."),
        ("Emberkit", "Carries a spark that grows whenever you start on time."),
        ("Flamefang", "Nips at hesitation until action catches fire."),
        ("Sunpup", "Basks in streaks that survive even your low-energy days."),
        ("Blazeling", "Crackles brightest when you finish the hardest task first."),
        ("Inferfox", "A wildfire spirit that answers only to fearless momentum."),
        ("Sparklet", "A tiny ember that refuses to let the day go dark."),
        ("Volthop", "Jumps between tasks the instant your energy spikes."),
        ("Zaprat", "Chews through distraction like frayed wiring."),
        ("Thunderbug", "Strikes hardest during short bursts of sharp execution."),
        ("Sparkleon", "Glows whenever a messy idea finally clicks into place."),
        ("Boltiger", "Charges across impossible workloads without slowing."),
        ("Chargepup", "Stores the last bit of willpower you thought you lost."),
        ("Frostling", "Keeps calm in the cold silence before hard work begins."),
        ("Icetail", "Slides through routine with patient, steady rhythm."),
        ("Chillpup", "Never panics, even when deadlines breathe down your neck."),
        ("Snowfang", "Protects fragile streaks through the harshest days."),
        ("Blizzard", "Descends when discipline holds through total burnout."),
        ("Cryopup", "A quiet companion for lonely, focused winter nights."),
        ("Metalwing", "Glides through pressure with mechanical precision."),
        ("Ironclaw", "Grips tightly to routines that others abandon."),
        ("Steelite", "Hardens every time you follow through under stress."),
        ("Gearbox", "Turns scattered effort into systems that actually hold."),
        ("Forgebug", "Forged from repetition, pressure, and impossible standards."),
        ("Bolthead", "Pins your wandering focus back where it belongs."),
        ("Mindbug", "Nests in quiet moments before a breakthrough."),
        ("Psychling", "Small but strangely aware of every mental shortcut."),
        ("Brainfly", "Circles around difficult ideas until they finally land."),
        ("Thoughtox", "Pushes through mental fog with stubborn clarity."),
        ("Dreamweaver", "Turns long-focus sessions into visions of impossible work."),
        ("Wisppup", "Appears when your mind wanders, then gently leads it back."),
        ("Strikeleon", "Lunges at tasks the second doubt shows weakness."),
        ("Brawlrat", "Scrappy and relentless, it never quits the daily grind."),
        ("Fistling", "Hits hardest when you stop overthinking and act."),
        ("Blockox", "Stands between you and every incoming excuse."),
        ("Warchampion", "A battle-forged myth born from brutal consistency."),
        ("Kickscoot", "Keeps momentum moving even when motivation disappears."),
        ("Windrix", "Drifts in when the day feels light and possible."),
        ("Gustbug", "Tiny, restless, and always pushing the next action forward."),
        ("Feathersnap", "Changes direction instantly when focus sharpens."),
        ("Skyhopper", "Leaps between ideas until one becomes real."),
        ("Cloudpup", "Floats beside calm mornings and clean starts."),
        ("Stormwing", "A skyborn omen that arrives before your strongest runs."),
    ]

    for name, flavor_text in flavor_updates:
        cur.execute(
            f"""
            UPDATE monsters
            SET flavor_text = {PLACEHOLDER}
            WHERE name = {PLACEHOLDER}
              AND (flavor_text IS NULL OR flavor_text = '')
            """,
            (flavor_text, name),
        )

def fuse_duplicate_monsters(user_id):
    """
    Finds groups of 3+ identical non-shiny monsters belonging to user.
    For each group of 3, deletes 3 non-shiny, outputs 1 shiny of the same type.
    Returns number of new shiny monsters created.
    """
    from db.pool import get_cursor, PLACEHOLDER
    from utils import format_date_iso, utc_today
    import logging
    
    logger = logging.getLogger(__name__)
    today = format_date_iso(utc_today())
    shinies_created = 0
    
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT monster_id, COUNT(*) as cnt 
            FROM user_monsters 
            WHERE user_id = {PLACEHOLDER} AND is_shiny = 0 
            GROUP BY monster_id 
            HAVING COUNT(*) >= 3
            """,
            (user_id,)
        )
        duplicates = cur.fetchall()
        
        for dup in duplicates:
            monster_id = dup["monster_id"]
            count = dup["cnt"]
            fusions_possible = count // 3
            
            for _ in range(fusions_possible):
                cur.execute(
                    f"""
                    DELETE FROM user_monsters 
                    WHERE id IN (
                        SELECT id FROM user_monsters 
                        WHERE user_id = {PLACEHOLDER} AND monster_id = {PLACEHOLDER} AND is_shiny = 0 
                        LIMIT 3
                    )
                    """,
                    (user_id, monster_id)
                )
                
                cur.execute(
                    f"""
                    INSERT INTO user_monsters (user_id, monster_id, caught_date, is_shiny)
                    VALUES ({PLACEHOLDER}, {PLACEHOLDER}, {PLACEHOLDER}, 1)
                    """,
                    (user_id, monster_id, today)
                )
                shinies_created += 1
                
        if shinies_created > 0:
            logger.info("Monsters Fused", extra={"metric": "monster_fused", "user_id": user_id, "metric_value": shinies_created})
            
    return shinies_created
