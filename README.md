# Personal Monitor — Backend (FastAPI)

REST API for the Personal Monitor app: JWT auth, health records (BMI), and finance tracking (money sources + transactions).

## Stack

- FastAPI + Uvicorn
- SQLAlchemy ORM
- JWT auth (python-jose) + bcrypt password hashing
- SQLite by default, Postgres/Neon via `DATABASE_URL`

## Setup

```bash
cd personal-monitor-backend
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # optional, edit as needed
```

## Run

```bash
uvicorn main:app --reload --port 8000
```

- API root: http://localhost:8000
- Interactive docs: http://localhost:8000/docs

Tables are created automatically on startup. There is no UI for registration, so create your user first:

```bash
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"me\", \"password\": \"secret\"}"
```

## Key endpoints

| Method | Path | Description |
| ------ | ---- | ----------- |
| POST | `/register` | Create a user |
| POST | `/token` | Login, returns JWT (form-encoded) |
| GET | `/api/me` | Current user |
| GET/POST | `/api/health` | List / create health records |
| PUT/DELETE | `/api/health/{id}` | Update / delete a record |
| GET/POST | `/api/sources` | List / create money sources |
| GET/POST | `/api/transactions` | List / create transactions |
| DELETE | `/api/transactions/{id}` | Delete a transaction |

All `/api/*` routes (except `/api/me` semantics) require an `Authorization: Bearer <token>` header.
