# Project Tracking System

A stand-alone web application for tracking projects, the people assigned to them, their deliverables and their budgets, with real-time visibility into project health and team capacity.

- **Frontend:** React 19 (Vite) with hand-written HTML/CSS — no UI libraries
- **Backend:** Python 3.13 AWS Lambda functions (one per service)
- **Database:** PostgreSQL (Aurora Serverless v2 on AWS)
- **Infrastructure:** Terraform; shell scripts for local development and deployment
- **Hosting:** S3 + CloudFront (UI), Lambda Function URLs behind CloudFront (`/api/*`), RDS Aurora

```
Browser ─► CloudFront ─┬─► S3 (React build)
                       └─► /api/<service>* ─► Lambda (Python) ─► Aurora PostgreSQL
Local:  Vite :3000 ─► proxy :3001 ─► LocalStack Lambdas ─► local PostgreSQL :5432
```

## Roles

| Capability | Admin | Manager | Employee |
|---|---|---|---|
| Create users (any role, including admins) | ✓ | | |
| Update user information | anyone, any field | own name/email | own name/email only |
| Create projects | ✓ | submits a **project request** | |
| Approve / reject project requests | ✓ | | |
| Edit projects | all | projects they manage | |
| Archive / reactivate projects | ✓ | | |
| Assign a project's manager | ✓ | | |
| Assign people to projects | anyone | their direct reports, on projects they manage | |
| Deliverables and budget items | all projects | projects they manage | view deliverables on assigned projects |
| See projects | all | projects they manage | projects currently assigned to them |
| See salary | all | direct reports | own |

### Business rules

- **Projects are never deleted.** Admins archive them (`is_archived`, `archived_at`, `archived_by`); archived projects are read-only, hidden by default, and can be reactivated. Every change is recorded in `audit_log`.
- **Credentials are generated.** Creating a user generates an **employee ID** (`EMP0001`, …) and a **random 6-character password**. The password is shown once to the admin and stored only as a PBKDF2 hash. Users sign in with employee ID + password; admins can reset a password.
- **One manager per person** (`users.manager_id`), with reporting-cycle checks.
- **40-hour week.** A person can be assigned to many projects, but their weekly hours across non-archived projects cannot exceed 40 (8 h × 5 days). Reactivating a project re-checks this for its team.
- Employees can change only their first name, last name and email.

## Repository layout

```
backend/
  _shared/            shared code, copied into each service as `shared/` by bin/sync-shared.sh
  auth/               POST /login, POST /refresh, GET /me
  users/              users, profile (/me), reset-password, workload
  projects/           projects, archive/reactivate, summary, dashboard
  project-requests/   manager requests, admin approve/reject
  assignments/        project assignments (40-hour rule)
  deliverables/       deliverables per project
  budgets/            planned vs actual budget items
  tests/              pytest suite (runs handlers against a local PostgreSQL test DB)
frontend/             React app (src/pages, src/components, src/api, src/auth, src/router)
infra/                Terraform (Lambda, Function URLs, CloudFront, S3, Aurora)
bin/                  start-dev.sh, deploy-backend.sh, deploy-frontend.sh, sync-shared.sh, …
```

Each folder under `backend/` with a `requirements.txt` becomes a Lambda named `coding-workshop-<folder>-<app id>` and is served at `/api/<folder>`.

## API

All endpoints take and return JSON and require `Authorization: Bearer <access token>` except login and refresh. List endpoints accept `q` (search), resource-specific filters, `sort` (`field` or `-field`), `page` and `page_size`, and return `{items, total, page, page_size}`. Errors share one shape: `{"error": {"code", "message", "details"}}` with 400/401/403/404/405/409/500.

| Service | Routes |
|---|---|
| `/api/auth` | `POST /login`, `POST /refresh`, `GET /me` |
| `/api/users` | `GET /`, `POST /`, `GET|PUT /me`, `GET|PUT /{id}`, `POST /{id}/reset-password`, `GET /{id}/workload` |
| `/api/projects` | `GET /`, `POST /`, `GET /dashboard`, `GET|PUT /{id}`, `POST /{id}/archive`, `POST /{id}/reactivate`, `GET /{id}/summary` |
| `/api/project-requests` | `GET /`, `POST /`, `GET|PUT /{id}`, `POST /{id}/withdraw`, `POST /{id}/approve`, `POST /{id}/reject` |
| `/api/assignments` | `GET /`, `POST /`, `GET|PUT|DELETE /{id}` |
| `/api/deliverables` | `GET /`, `POST /`, `GET|PUT|DELETE /{id}` |
| `/api/budgets` | `GET /` (includes `totals`), `POST /`, `GET|PUT|DELETE /{id}` |

The schema is created automatically (idempotently) on each Lambda's first request, and the first admin is seeded from `ADMIN_EMPLOYEE_ID` / `ADMIN_PASSWORD`.

## Local development

Prerequisites come from the workshop setup (`bin/setup-environment.sh`): Python 3.13, Node 22, Docker, LocalStack, Terraform, AWS CLI and PostgreSQL (`postgres` / `postgres123`).

```bash
./bin/start-dev.sh          # PostgreSQL + LocalStack + Lambdas + proxy (:3001) + Vite (:3000)
```

Open http://localhost:3000 and sign in as the seeded admin:

```bash
cd infra
terraform output admin_employee_id      # ADMIN001
terraform output -raw admin_password    # generated 6-character password
```

After changing backend code, run `./bin/sync-shared.sh` (LocalStack hot-reloads the service folders).

## Tests

```bash
# Backend: unit + integration tests against a local PostgreSQL database "pts_test"
python3.13 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/python -m pytest --cov=. --cov-report=term-missing
../.venv/bin/bandit -r . -x ./tests

# Frontend: Vitest + Testing Library, ESLint, production build
cd frontend && npm install && npm run lint && npm test && npm run build
```

```bash
# End-to-end smoke test against a running stack (local proxy or CloudFront URL).
# Creates throwaway users/projects, checks the role rules and the 40-hour limit, then
# deactivates/archives what it created.
./bin/smoke-test.py --url http://localhost:3001 --admin-password "$(terraform -chdir=infra output -raw admin_password)"
```

## Deploying to AWS

```bash
./bin/deploy-backend.sh aws     # terraform apply: Aurora, Lambdas, CloudFront, S3
./bin/deploy-frontend.sh aws    # build the React app and sync it to S3, invalidate CloudFront
```

`deploy-backend.sh` fetches temporary workshop credentials into `ENVIRONMENT.config` (never committed). The site URL is `terraform -chdir=infra output website_url`; the admin password is `terraform -chdir=infra output -raw admin_password`.
