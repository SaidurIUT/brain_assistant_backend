# Brain Assistant Backend

FastAPI backend for Brain Assistant.

## Ports

This service deliberately avoids the existing workspace ports listed in the root README.

- FastAPI: `8010`
- Backend Postgres host port: `55432`
- Backend database name: `brain_assistant_backend`
- Dev email is delivered through the Brain Assistant backend Mailhog only:
  - SMTP host port: `1125`
  - Web UI: `8125`
  - Open the inbox at http://localhost:8125. Port `1125` is SMTP only and will not render in a browser.

## Local Run With Docker

```sh
cd backend
cp .env.example .env
docker compose up --build
```

This starts the backend Postgres database, the backend-only Mailhog service, runs Alembic migrations, and serves FastAPI on http://localhost:8010.

If the database is already running because you started it separately, use:

```sh
cd backend
docker compose up --build brain-assistant-api
```

## Local Run Without Docker API

Only use this path if you want to run FastAPI directly on your machine. The active Python environment must have the backend dependencies installed first.

```sh
cd backend
python -m pip install -e ".[dev]"
docker compose up -d brain-assistant-db brain-assistant-mailhog
python -m alembic upgrade head
python -m fastapi dev app/main.py --host 0.0.0.0 --port 8010
```

## Auth Flow

- Register with any valid email address.
- Registration creates a default company workspace, administrator membership, and brand settings record, then sends an email verification link.
- Users can continue onboarding before verification, but member invitations are blocked until email verification is completed.
- `POST /api/v1/auth/verify-email` verifies the email token and starts the first session.
- Login returns a short-lived access token and sets a refresh token in an HttpOnly cookie.
- Refresh tokens are opaque, stored hashed in Postgres, rotated on every refresh, and revoked on reuse.
- Logout revokes the current refresh session.
- Logout-all revokes every active session for the user.
- Administrators invite members from settings; invited people receive an email and set their first password through `POST /api/v1/auth/accept-invitation`.

## Email Modes

Development uses Mailhog:

```text
MAIL_MODE=dev
SMTP_HOST=localhost
SMTP_PORT=1125
```

When the API runs inside Docker, `backend/docker-compose.yml` starts its own `brain-assistant-mailhog` service and points `SMTP_HOST` to that container. It does not use the Chatwoot Mailhog service.

Production requires real SMTP credentials:

```text
MAIL_MODE=production
MAIL_FROM=Brain Assistant <support@example.com>
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_STARTTLS=true
```

## Settings Flow

- `GET /api/v1/settings` returns the current user, selected company, brand settings, members, and the user's active workspaces.
- Pass `company_id` to settings routes to manage or view a specific workspace when the user belongs to more than one organization.
- `PATCH /api/v1/settings/user` changes first and last name.
- `PATCH /api/v1/settings/company` changes company details.
- `PATCH /api/v1/settings/brand` changes whitelabel/brand details.
- `POST /api/v1/settings/members` adds a workspace member with `administrator`, `manager`, `agent`, or `viewer` role.
- `PATCH /api/v1/settings/members/{id}/role` changes a member role.
