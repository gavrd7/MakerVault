#!/usr/bin/env bash
set -euo pipefail

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "This directory is already a Git repository."
  exit 0
fi

git init -b main
git add .
git commit -m "Initial MakerVault import"

echo
echo "Git repository created on branch 'main'."
echo "Create an empty private remote repository, then run:"
echo "  git remote add origin <YOUR-REPOSITORY-URL>"
echo "  git push -u origin main"
