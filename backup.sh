#!/usr/bin/env bash
# soroban 账本备份（WAL 安全）。用 sqlite3 .backup 而非裸 copy，避免漏掉 -wal 未 checkpoint 的数据。
# 建议加进 cron，例如每天 03:00：  0 3 * * * /path/to/soroban/backup.sh >> /path/to/soroban/backups/backup.log 2>&1
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB="$ROOT/backend/soroban.db"
OUT="$ROOT/backups"

[ -f "$DB" ] || { echo "找不到数据库 $DB"; exit 1; }
mkdir -p "$OUT"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$OUT/soroban-$STAMP.db"

sqlite3 "$DB" ".backup '$DEST'"
echo "已备份 → $DEST"

# 只保留最近 30 份
ls -1t "$OUT"/soroban-*.db 2>/dev/null | tail -n +31 | xargs -r rm -f
