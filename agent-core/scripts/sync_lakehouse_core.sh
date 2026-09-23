#!/usr/bin/env bash
# lakehouse-core/ dizinini veri dalının güncel ucundan yeniden anlık görüntüler (M01-T01/T02).
# Tarihçe veri dalında kalır; burada yalnız ağaç durur. Kullanım: scripts/sync_lakehouse_core.sh [dal]
set -euo pipefail
BRANCH="${1:-feature/lakehouse-catalog-breadth}"
cd "$(git rev-parse --show-toplevel)"
git fetch -q origin "$BRANCH"
SHA=$(git rev-parse --short "origin/$BRANCH")
git rm -r -q --cached lakehouse-core >/dev/null 2>&1 || true
rm -rf lakehouse-core
git read-tree --prefix=lakehouse-core/ -u "origin/$BRANCH:lakehouse-core"
echo "lakehouse-core ← origin/$BRANCH@$SHA (ağaç anlık görüntüsü; commit et ve docs/calisma-notlari/M01_ORTAM.md'de sha'yı güncelle)"
