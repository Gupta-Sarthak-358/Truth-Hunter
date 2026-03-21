# Truth Hunter

Truth Hunter is a Flask-based productivity app with task tracking, streaks, badges, and monster collection/gamification.

## Stack

- Python
- Flask
- PostgreSQL
- Gunicorn
- Render-ready deployment

## Features

- Daily and recurring tasks
- Categories with monster type mapping
- Streaks, XP, and levels
- Badge and freeze rewards
- Monster collection and recent catches
- In-process caching and cache prewarming for better UX

## Local Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a local env file from the example:

```bash
cp .env.example .env
```

4. Set:

- `SECRET_KEY`
- `DATABASE_URL`

5. Run the app:

```bash
python run.py
```

## Environment Variables

Required:

- `SECRET_KEY`
- `DATABASE_URL`

Common:

- `FLASK_ENV`
- `SESSION_COOKIE_SECURE`

## Deployment

This project is configured for Render.

- Build command:

```bash
pip install -r requirements.txt
```

- Start command:

```bash
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120 --log-level info
```

Recommended Render setup:

1. Deploy as a Python web service.
2. Set `DATABASE_URL` to your Render Postgres internal URL.
3. Set `SECRET_KEY` to a strong random value.
4. Set `FLASK_ENV=production`.
5. Keep the web service and database in the same region.

## Notes

- Do not commit your real `.env`.
- The app initializes required tables and indexes on startup.
- The included `Procfile` is already suitable for Render.
