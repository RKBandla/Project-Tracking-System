# Project Tracking System

A stand-alone web application for tracking projects, the people booked on them, their deliverables and their budgets, with real-time visibility into project health, resource allocation and delivery progress.

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

## What the MVP builds

| Requirement | How |
|---|---|
| Authentication and authorization | Log in with a username (first and last name) or email, and a password; signed JWT that expires (1 h, refreshable for 7 days); passwords hashed (PBKDF2) |
| Role-based access control | Admin, Manager, Employee — the server checks the role on every request |
| CRUD for projects | Create, view, edit, archive and reactivate |
| CRUD for deliverables | Same, per project, plus "depends on" links between deliverables; any deliverable can be marked as a **milestone** (a checkpoint with a single date, shown as ◆) |
| CRUD for resources | Book a person onto a project for N hours per week over a date range |
| CRUD for budget tracking | A budget per project; planned cost comes from bookings, consumed cost from approved logged hours |
| Search and filter | Name search and status filter on every list, done on the server, paginated |
| Responsive design | Tables turn into cards on phones; the allocation grid, timeline and dependency view scroll sideways |

## Who can do what

| | Admin | Manager | Employee |
|---|---|---|---|
| Create users, set roles | yes | no | no |
| Create projects, assign their manager | yes | no, files a request | no |
| Approve project requests | yes | no | no |
| Edit a project | all fields | own projects: description and status | no |
| Deliverables, resources and budget on a project | yes | own projects | view if assigned |
| Book people onto projects | yes | own projects, anyone in the company | no |
| Log hours | no | no | own, on booked projects |
| Approve logged hours | yes, anyone | their direct reports | no |
| See projects | all | the ones they manage | the ones they're booked on |
| Edit own name and email | yes | yes | yes |

Nobody changes their own role or salary.

## Rules the app enforces (each one demoable as a refusal)

1. **Nobody is booked over 40 hours in any week**, across all projects. The 41st hour is refused (409) and the response names the conflicting projects.
2. **Nothing is deleted.** Records are archived (or withdrawn) and can be reactivated, so cost history survives. There is no DELETE route.
3. **Deliverable dependencies can't loop.** A link that would create a cycle is refused and the loop is named.
4. **A deliverable can't be marked done while something it depends on isn't.** A milestone needs a date and has no separate start date.
5. **Money is whole cents.** Budgets, salaries and costs are integers on the server, formatted only on screen.
6. **Only approved hours count as consumed.**
7. **Every change is recorded.** Each create, edit or archive writes one audit-log row, and everyone above the actor in the reporting line gets an in-app notification.
8. **Another manager's project answers "not found"**, not "forbidden", so ids can't be probed.
9. **Emails are made from the person's name.** The part before `@` must be the full name or the initials, so Eli Engineer can be `eli.engineer@`, `eliengineer@` or `ee@`. If two people share a name, the password tells them apart; if that's still ambiguous, they sign in with their email.

## How the money works

```text
hourly rate   = annual salary / 2080            (40 h x 52 weeks)
planned cost  = sum of (hours per week x weeks in booking x hourly rate)
consumed cost = sum of (approved logged hours x hourly rate)
at risk       = past end date and not complete, OR a deliverable overdue,
                OR consumed share of budget > elapsed share of schedule + 15%
```

## Screens

Login · Dashboard (status, at-risk with reasons, budget, capacity) · Projects (list and detail with Overview, Deliverables list/timeline, Dependencies, Resources and Budget tabs) · Allocation grid · People · My timesheet · Hours to approve · Project requests · Notifications · Audit log (admin) · My profile

| Question | Where |
|---|---|
| What is the status of each active project? | Projects list, status column |
| Which projects are at risk of missing deadlines? | Dashboard "At risk" panel, with the reason |
| How are resources allocated across projects? | Allocation grid: people down, weeks across |
| What are the key deliverables and their completion status? | Deliverables tab: list and timeline (milestones as ◆); dashboard "Upcoming milestones" |
| Which team members are over-allocated? | Allocation grid: cells at/over 40 h flagged; dashboard "Fully booked" |
| What is the dependency chain between deliverables? | Dependencies tab on the project |
| How much budget is consumed versus planned? | Budget bar on the project, projects list and dashboard |

## Repository layout

```
backend/
  _shared/            shared code, copied into each service as `shared/` by bin/sync-shared.sh
  auth/               log in with username or email, refresh, me
  users/              people, profile (/me), reset-password, weekly workload
  projects/           projects, archive/reactivate, summary, dashboard, at-risk
  project-requests/   manager requests, admin approve/reject
  assignments/        bookings over date ranges (40 h/week rule), allocation grid
  deliverables/       deliverables, dependencies, dependency graph
  budgets/            budget vs planned vs consumed, per-person breakdown
  timesheets/         log hours, approve/reject
  activity/           notifications and audit log
  tests/              pytest suite (runs handlers against a local PostgreSQL test DB)
frontend/             React app (src/pages, src/components, src/api, src/auth, src/router)
infra/                Terraform (Lambda, Function URLs, CloudFront, S3, Aurora)
bin/                  start-dev.sh, deploy-backend.sh, deploy-frontend.sh, sync-shared.sh, smoke-test.py
```

Each folder under `backend/` with a `requirements.txt` becomes a Lambda named `coding-workshop-<folder>-<app id>` and is served at `/api/<folder>`.

### MVC inside each service

Everything about one feature lives in its folder, split into Model, View and Controller files
(named after the feature so they're easy to find with Ctrl+P):

```
backend/users/
  function.py           AWS Lambda entry point only (AWS looks for this name)
  users_controller.py   CONTROLLER: routes - check the request and the rules, call the model, return a view
  users_model.py        MODEL: every SQL query for this feature
  users_view.py         VIEW: the JSON sent back
```

`backend/_shared/` holds what every feature uses: the tables (`schema.py`), the database connection, login
tokens, role checks (`rbac.py`), the 40-hour rule, cost and risk SQL, validation and the audit log.

## API

All endpoints take and return JSON and require `Authorization: Bearer <access token>` except login and refresh. List endpoints accept `q` (search), resource-specific filters, `sort` (`field` or `-field`), `page` and `page_size`, and return `{items, total, page, page_size}`. Errors share one shape: `{"error": {"code", "message", "details"}}` with 400/401/403/404/405/409/500.

| Service | Routes |
|---|---|
| `/api/auth` | `POST /login` (`{login, password}` where `login` is "First Last" or an email), `POST /refresh`, `GET /me` |
| `/api/users` | `GET /`, `POST /`, `GET|PUT /me`, `GET|PUT /{id}`, `POST /{id}/reset-password`, `GET /{id}/workload` |
| `/api/projects` | `GET /`, `POST /`, `GET /dashboard`, `GET|PUT /{id}`, `POST /{id}/archive`, `POST /{id}/reactivate`, `GET /{id}/summary` |
| `/api/project-requests` | `GET /`, `POST /`, `GET|PUT /{id}`, `POST /{id}/withdraw`, `POST /{id}/approve`, `POST /{id}/reject` |
| `/api/assignments` | `GET /`, `GET /grid`, `POST /`, `GET|PUT /{id}`, `POST /{id}/archive`, `POST /{id}/reactivate` |
| `/api/deliverables` | `GET /` (`?milestone=true`), `GET /graph`, `POST /`, `GET|PUT /{id}` (incl. `depends_on`, `is_milestone`), `POST /{id}/archive`, `POST /{id}/reactivate` |
| `/api/budgets` | `GET /`, `GET /{project id}`, `PUT /{project id}` |
| `/api/timesheets` | `GET /`, `GET /week`, `POST /`, `PUT /{id}`, `POST /{id}/withdraw`, `POST /{id}/approve`, `POST /{id}/reject`, `POST /approve-batch` |
| `/api/activity` | `GET /notifications`, `POST /notifications/read-all`, `POST /notifications/{id}/read`, `GET /audit` |

The schema is created automatically (idempotently) on each Lambda's first request, and the first admin is seeded from `ADMIN_EMAIL` / `ADMIN_PASSWORD`. A version-1 development database is rebuilt automatically the first time version 2 runs.

## Local development

Prerequisites come from the workshop setup (`bin/setup-environment.sh`): Python 3.13, Node 22, Docker, LocalStack, Terraform, AWS CLI and PostgreSQL (`postgres` / `postgres123`).

```bash
./bin/start-dev.sh          # PostgreSQL + LocalStack + Lambdas + proxy (:3001) + Vite (:3000)
```

Open http://localhost:3000 and sign in as the seeded admin:

```bash
cd infra
terraform output admin_email            # admin@pts.local
terraform output -raw admin_password    # generated 6-character password
```

To fill the app with demo data (two managers, four employees, three projects in different states, bookings,
dependencies, logged and approved hours) and print everyone's sign-in details:

```bash
./bin/seed-demo.py --url http://localhost:3001 --admin-password "$(terraform -chdir=infra output -raw admin_password)"
```

After changing backend code, run `./bin/sync-shared.sh` (LocalStack hot-reloads the service folders).

## Tests

```bash
# Backend: unit + integration tests against a local PostgreSQL database "pts_test"
python3.13 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/python -m pytest --cov=. --cov-report=term-missing
../.venv/bin/bandit -q _shared/*.py */function.py */*_controller.py */*_model.py */*_view.py

# Frontend: Vitest + Testing Library, ESLint, production build
cd frontend && npm install && npm run lint && npm test && npm run build
```

```bash
# End-to-end smoke test against a running stack (local proxy or CloudFront URL).
# Creates throwaway users/projects, demonstrates every rule as a refusal, then
# deactivates/archives what it created.
./bin/smoke-test.py --url http://localhost:3001 --admin-password "$(terraform -chdir=infra output -raw admin_password)"
```

## Deploying to AWS

```bash
./bin/deploy-backend.sh aws     # terraform apply: Aurora, Lambdas, CloudFront, S3
./bin/deploy-frontend.sh aws    # build the React app and sync it to S3, invalidate CloudFront
```

`deploy-backend.sh` fetches temporary workshop credentials into `ENVIRONMENT.config` (never committed). The site URL is `terraform -chdir=infra output website_url`; the admin login is `terraform -chdir=infra output admin_email` and `terraform -chdir=infra output -raw admin_password`.
