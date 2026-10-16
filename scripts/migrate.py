# -*- coding: utf-8 -*-
# scripts/migrate.py
"""
ST-012 -- apply database/migrations/NNN_*.sql to the stratrad database, in order, once each.

Each migration runs in its own transaction together with its row in `schema_migrations` (version, name, sha256,
applied_at): it is all applied or not at all. Already-applied versions are skipped; an applied file whose content has
changed is refused (write a new migration instead). Runs as stratrad_app (STRATRAD_DB_URL).

Usage (repo root): python -m scripts.migrate [--status]
"""

import argparse
import hashlib
import logging
import re
import sys
from datetime import date
from pathlib import Path

from core.config import LOG_DIR, REPO_ROOT
from core.db import connect

logger = logging.getLogger('migrate')
MIGRATIONS_DIR = REPO_ROOT / 'database' / 'migrations'
NAME_RE = re.compile(r'^(\d{3})_[a-z0-9_]+\.sql$')
CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    integer PRIMARY KEY,
    name       text NOT NULL,
    sha256     text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)"""


def discover(folder: Path = MIGRATIONS_DIR) -> list[tuple[int, str, str, str]]:
    """(version, file name, sha256, sql) for every migration file, sorted; refuses bad names and duplicate versions."""
    out = []
    for f in sorted(folder.glob('*.sql')):
        m = NAME_RE.match(f.name)
        if not m:
            raise ValueError(f'bad migration file name {f.name} (expected NNN_lower_snake.sql)')
        sql = f.read_text(encoding='utf-8')
        out.append((int(m.group(1)), f.name, hashlib.sha256(sql.encode('utf-8')).hexdigest(), sql))
    versions = [v for v, *_ in out]
    if len(versions) != len(set(versions)):
        raise ValueError(f'duplicate migration versions: {sorted(v for v in versions if versions.count(v) > 1)}')
    return out


def plan(files: list[tuple[int, str, str, str]], applied: dict[int, tuple[str, str]]) -> list[tuple[int, str, str, str]]:
    """Migrations still to apply. Raises when an applied version's file changed or disappeared."""
    by_version = {v: (n, h) for v, n, h, _ in files}
    for v, (name, sha) in applied.items():
        if v not in by_version:
            raise ValueError(f'applied migration {v:03d} ({name}) is missing from {MIGRATIONS_DIR}')
        if by_version[v][1] != sha:
            raise ValueError(f'applied migration {v:03d} ({name}) has changed since it was applied; write a new one')
    return [f for f in files if f[0] not in applied]


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--status', action='store_true', help='list applied and pending migrations, change nothing')
    args = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(LOG_DIR / f'migrate_{date.today():%Y%m%d}.log', encoding='utf-8')])
    files = discover()
    with connect('app') as conn:
        conn.execute(CREATE_TABLE)
        conn.commit()
        applied = {v: (n, h) for v, n, h in conn.execute('SELECT version, name, sha256 FROM schema_migrations')}
        todo = plan(files, applied)
        logger.info(f'applied {sorted(applied)}; pending {[v for v, *_ in todo]}')
        if args.status:
            return 0
        for v, name, sha, sql in todo:
            with conn.transaction():
                conn.execute(sql)
                conn.execute('INSERT INTO schema_migrations (version, name, sha256) VALUES (%s, %s, %s)', (v, name, sha))
            logger.info(f'applied {name}')
    logger.info(f'RESULT: OK ({len(todo)} applied)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
