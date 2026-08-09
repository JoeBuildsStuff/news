#!/usr/bin/env bash
# Point this clone at the tracked hooks in .githooks/ (repo-local git config).
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

git config core.hooksPath .githooks
chmod +x .githooks/pre-commit

echo "Installed git hooksPath=.githooks"
echo "Commits that stage web/ files will run: cd web && pnpm run lint"
