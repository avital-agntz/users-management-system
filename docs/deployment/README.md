# AWS deployment: decisions

```text
Browser → HTTPS (Nginx on EC2) → FastAPI (Docker on EC2) → RDS PostgreSQL (private)
```

Region `us-east-1`. Every resource is named `users-management-dev-<resource>` and tagged
`Project=users-management`, `Environment=dev`, `Owner=avital`. This file contains no secrets.

## Why Nginx in production?

FastAPI can receive requests directly. In this deployment, Nginx is the public entry
point: it handles HTTPS certificates and encryption, serves frontend files, and
forwards API requests to FastAPI through a localhost-only port. It also provides
a central place to configure request-size limits, connection timeouts, and web
access logs. This separates public web traffic management from application logic;
Nginx is an operational choice, not a requirement for FastAPI to work.

## 2.1 Deployment configuration ✅

| Item | Choice | Reason |
|---|---|---|
| Region | `us-east-1` | Existing CLI default; all required services; among the cheapest Regions. |
| EC2 | `t3.small` (2 vCPU, 2 GB), 20 GB gp3 | FastAPI, Redis, Nginx, and the CloudWatch agent need more than 1 GB of memory. |
| RDS | `db.t4g.micro` (2 vCPU, 1 GB), PostgreSQL 17, Single-AZ, 20 GB gp3 | The smallest class that fits; the same PostgreSQL version as local, where tests pass. |
| Sizes recorded | This table | Needed for the load comparisons in Section 4. |
| Tags | See above | Find every project resource at cleanup; split costs by project. |
| Cost estimate | **≈ $42.69/month**; see below | Official prices (Pricing Calculator and the RDS console). |
| Budget | `users-management-dev-monthly`: $70, email alerts at 70%, 85%, 100% | Early warning on unexpected spending. |
| Test data | Synthetic users only (`*@example.com`) | No real personal data in a test deployment. |
| Single point of failure | One EC2 instance | If it stops, the site is down; several instances behind a load balancer would fix this (out of scope). |

**Open follow-up:** the account is shared, so the budget currently counts all company
costs. Filtering it by the `Project` tag requires Billing access from an admin (requested).

### Monthly cost (On-Demand, 730 hours)

| Service | Configuration | USD |
|---|---|---|
| EC2 | `t3.small` + 20 GB gp3 | 16.78 |
| RDS | `db.t4g.micro`, Single-AZ, 20 GB gp3 (RDS console estimate) | 13.98 |
| Public IPv4 | 1 address | 3.65 |
| CloudWatch | 10 metrics, 1 dashboard, 10 alarms, 1 GB logs, Synthetics every 15 minutes | 7.88 |
| Secrets Manager | 1 secret (the RDS password) | 0.40 |
| SNS | Alarm emails (first 1,000 per month are free) | 0.00 |
| **Total** | | **≈ 42.69** |

Source: [Pricing Calculator](https://calculator.aws/#/estimate?id=a9fa764c3e098c1658eb93c132d413574e183706).
Left off on purpose: RDS Extended Support, Enhanced Monitoring, Multi-AZ, and storage autoscaling.
**Cost note:** stopping EC2 or RDS still charges for disks and the IP, and AWS restarts a
stopped RDS database after 7 days. Only deleting the resources stops every cost.

## 2.2 RDS and application connection ✅

| Item | Status | Choice and reason |
|---|---|---|
| RDS in the same VPC as EC2 | ✅ | Default VPC, shared with the EC2 security group. |
| No public access | ✅ | Public access: No; the database has no internet address. |
| Encryption and backups | ✅ | Encrypted with the `aws/rds` key; automated backups kept 7 days; deletion protection on. |
| DB security group | ✅ | `users-management-dev-db-sg` allows port 5432 only from `users-management-dev-app-sg` (the EC2 server), so only the app can reach the private database, even if the server's IP changes. |
| Credentials outside the repo | ✅ | The master password is generated and stored by AWS Secrets Manager. |
| PostgreSQL driver | ✅ | Already present (`psycopg`); the app was migrated from SQLite earlier. |
| RDS database URL | ✅ | Set only in the server's `.env`, built by `deploy/write-server-env.sh`; never committed. |
| Encrypted connection with certificate check | ✅ | `sslmode=verify-full` with the AWS RDS CA bundle baked into the image; migrations connected successfully. |
| Repeatable migration step | ✅ | One-off `migrate` service (`alembic upgrade head`); safe to re-run, it skips tables that already exist. |
| Migrations separate from startup | ✅ | The container only starts the API, so a failed migration shows up on its own and cannot block a restart. |
| App works against RDS | ✅ | From EC2: migration created the tables; `/health` healthy; register, login, and profile succeeded with a synthetic user. |
| No silent SQLite fallback | ✅ | With `APP_ENV=production`, the app refuses to start unless `DATABASE_URL` is PostgreSQL with `sslmode=verify-full`. |

## 2.3 EC2 server (in progress)

Design choices, decided before building:

| Choice | Decision | Reason |
|---|---|---|
| Operating system | Amazon Linux 2023 | Built for EC2; SSM Agent preinstalled; used in AWS docs. |
| Server access | Session Manager only; port 22 closed | No open door to the internet and no key files; every session is logged. |
| Public address | Elastic IP | Stays the same through stop/start, so the domain (2.4) always points to the server. |
| Code delivery | `git clone` and build on the server | Simple and free; the repo holds no secrets. |
| Secrets | Server-only `.env` (`chmod 600`), filled from Secrets Manager by a script | No code changes; the server role can read only this one secret (least privilege). |
| Redis | Docker on the same server, no published port | Cache only; losing it loses no data. |
| Auto-restart | `restart: unless-stopped` plus Docker enabled at boot | The app returns after a crash or reboot without manual steps. |
| Server compose file | Separate `docker-compose.ec2.yml` (`migrate`, `app`, `redis`) | No local database; the app listens only on `127.0.0.1:8000`, reachable only by Nginx. |

| Checklist item | Status | How it was verified |
|---|---|---|
| IAM role on EC2 | ✅ | `users-management-dev-ec2-role`: Session Manager access plus read access to the one RDS password secret. |
| Session Manager access | ✅ | Connected from the Console as `ssm-user` on Amazon Linux 2023. |
| Only ports 80 and 443 open | ✅ | `users-management-dev-app-sg` inbound: HTTP and HTTPS only. |
| SSH restricted | ✅ | No port 22 rule and no key pair; the Console's SSH connect fails as expected. |
| Docker, Compose, Git installed | ✅ | Installed with `dnf` plus the Compose and buildx plugins; Docker enabled at boot. |
| Backend bound to localhost | ✅ | `docker compose ps` shows `127.0.0.1:8000->8000`; reachable only from the server. |
| Redis private | ✅ | No published port; only the app container can reach it. |
| RDS URL and JWT secret on the server | ✅ | Written by `deploy/write-server-env.sh`; the password comes from Secrets Manager and is never printed. |
| Restricted secret file | ✅ | `.env` is `-rw-------` owned by root. |
| No reload mode | ✅ | The image runs plain `uvicorn`, without `--reload`. |
| Auto-restart | ✅ | `restart: unless-stopped` on `app` and `redis`; a reboot test follows in 2.5. |
| Nginx installed | Pending | Done together with its configuration in 2.4. |
