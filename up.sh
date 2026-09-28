#!/usr/bin/env bash
# One-shot: kind cluster -> Agent Substrate -> in-cluster Ollama -> kagent -> sample agents.
# Idempotent: re-run any time; each step skips/upgrades what already exists.
set -euo pipefail
cd "$(dirname "$0")"
for s in scripts/00-tools.sh scripts/01-cluster.sh scripts/02-substrate.sh scripts/03-ollama.sh scripts/04-kagent.sh scripts/05-agents.sh; do
  printf '\n\033[1;36m==> %s\033[0m\n' "$s"; "$s"
done
printf '\n\033[1;32mDone.\033[0m Run ./scripts/ui.sh, then open http://localhost:8080\n'
