# Brain Assistant Backend

FastAPI backend for Brain Assistant.

## Ports

This service deliberately avoids the existing workspace ports listed in the root README.

- FastAPI: `8010`
- Backend Postgres host port: `55432`
- Backend database name: `brain_assistant_backend`

## Local Run

```sh
cd backend
cp .env.example .env
docker compose up -d brain-assistant-db
alembic upgrade head
fastapi dev app/main.py --host 0.0.0.0 --port 8010
```

Or run both the API and database:

```sh
cd backend
docker compose up --build
```

## Auth Flow

- Register with any valid email address.
- Registration creates a default company workspace, administrator membership, and brand settings record.
- Login returns a short-lived access token and sets a refresh token in an HttpOnly cookie.
- Refresh tokens are opaque, stored hashed in Postgres, rotated on every refresh, and revoked on reuse.
- Logout revokes the current refresh session.
- Logout-all revokes every active session for the user.
- Email verification is intentionally not required yet.

## Settings Flow

- `GET /api/v1/settings` returns the current user, company, brand settings, and members.
- `PATCH /api/v1/settings/user` changes first and last name.
- `PATCH /api/v1/settings/company` changes company details.
- `PATCH /api/v1/settings/brand` changes whitelabel/brand details.
- `POST /api/v1/settings/members` adds a workspace member with `administrator`, `manager`, `agent`, or `viewer` role.
- `PATCH /api/v1/settings/members/{id}/role` changes a member role.
