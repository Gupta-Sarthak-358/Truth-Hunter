"""
Game Mechanics Constants

All game balancing values in one place for easy adjustment.
"""

# =======================
# XP & LEVELING
# =======================

XP_PER_TASK = 10
XP_PER_WEIGHTED_TASK = 15

XP_THRESHOLDS = [0, 100, 250, 500, 900, 1500, 2300, 3300, 4500, 6000]

# =======================
# MONSTER RARITY
# =======================

RARITY_CHANCE = {
    "legendary": 0.10,  # 10%
    "rare": 0.30,  # 30%
    "common": 0.60,  # 60%
}

# =======================
# SHINY CHANCE (Weekly)
# =======================

SHINY_THRESHOLDS = {
    5: 0.05,  # 5% for 5+ weekly completions
    15: 0.10,  # 10% for 15+ weekly completions
    30: 0.15,  # 15% for 30+ weekly completions
    50: 0.20,  # 20% for 50+ weekly completions
}

# =======================
# STREAK FREEZE
# =======================

FREEZE_USABLE_DAYS_GAP = 2  # Can recover streak if missed exactly 2 days

# =======================
# FREEZE AWARD MILESTONES
# =======================

FREEZE_STREAK_MILESTONE = 7  # Award freeze every 7 days of streak
FREEZE_MONSTER_MILESTONE = 15  # Award freeze every 15 unique monsters
FREEZE_BADGE_MILESTONE = 5  # Award freeze every 5 badges

# =======================
# PAGINATION
# =======================

MONSTERS_PER_PAGE = 24
HISTORY_DAYS_PER_PAGE = 20

# =======================
# TASK WEIGHTS
# =======================

DEFAULT_TASK_WEIGHT = 1
RECURRING_TASK_WEIGHT = 2
