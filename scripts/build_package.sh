#!/usr/bin/env bash
# Il pacchetto Python di Nazgarr (wheel + sdist in dist/), per l'installazione
# senza Docker: pipx install nazgarr-<versione>-py3-none-any.whl
#
#   scripts/build_package.sh [versione] [commit]
#
# Compila il frontend (Node serve solo qui, mai a runtime), copia lui e lo
# schema del DB in nazgarr/_assets e scrive la versione in nazgarr/_build_info.py.
set -euo pipefail
cd "$(dirname "$0")/.."

version="${1:-$(sed -n 's/^BASE_VERSION = "\(.*\)"/\1/p' nazgarr/version.py)}"
commit="${2:-$(git rev-parse --short HEAD 2>/dev/null || true)}"

(cd frontend && npm ci && npm run build)
rm -rf nazgarr/_assets
mkdir -p nazgarr/_assets
cp -R frontend/dist nazgarr/_assets/web
cp docs/schema.sql nazgarr/_assets/schema.sql
printf 'VERSION = "%s"\nCOMMIT = %s\n' "$version" "$( [ -n "$commit" ] && printf '"%s"' "$commit" || printf 'None')" \
  > nazgarr/_build_info.py

python -m pip install --quiet --upgrade build
rm -rf dist build
python -m build
echo "Built: $(ls dist)"
