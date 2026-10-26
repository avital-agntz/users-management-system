#!/usr/bin/env bash
# Build the server-only .env file for docker-compose.ec2.yml.
# Run on the EC2 server, from the repo folder, as root:
#   sudo deploy/write-server-env.sh <rds-secret-arn> <rds-endpoint>
# Re-run it after the RDS password rotates. Secrets are never printed.
set -euo pipefail

SECRET_ARN="${1:?Usage: write-server-env.sh <rds-secret-arn> <rds-endpoint>}"
RDS_ENDPOINT="${2:?Usage: write-server-env.sh <rds-secret-arn> <rds-endpoint>}"
ENV_FILE=".env"

# Read the RDS password from Secrets Manager (the server's IAM role may read only this secret)
# and URL-encode it, so special characters cannot break the database address.
DB_PASSWORD=$(
  aws secretsmanager get-secret-value --region us-east-1 --secret-id "$SECRET_ARN" \
    --query SecretString --output text |
  python3 -c 'import json, sys, urllib.parse; print(urllib.parse.quote(json.load(sys.stdin)["password"], safe=""))'
)

# Keep the existing JWT key, so re-running the script does not log every user out.
JWT_SECRET_KEY=$(grep -s '^JWT_SECRET_KEY=' "$ENV_FILE" | cut -d= -f2- || true)
JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(openssl rand -hex 32)}"

# umask 077: the new file is readable and writable by its owner (root) only.
umask 077
cat > "$ENV_FILE.tmp" <<EOF
APP_ENV=production
DATABASE_URL=postgresql+psycopg://app:${DB_PASSWORD}@${RDS_ENDPOINT}:5432/app?sslmode=verify-full&sslrootcert=/service/certs/global-bundle.pem
JWT_SECRET_KEY=${JWT_SECRET_KEY}
EOF
mv "$ENV_FILE.tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "Wrote $ENV_FILE (owner-only); keys: $(cut -d= -f1 "$ENV_FILE" | tr '\n' ' ')"
