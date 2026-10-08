# -*- coding: utf-8 -*-
# core/config.py
"""Central place for paths and settings read from the environment (.env at repo root)."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=REPO_ROOT / '.env')

LOG_DIR = REPO_ROOT / 'logs'


def _dir_from_env(var: str, default: Path | None = None) -> Path | None:
    """Return the directory named by env var `var`, or `default` when unset/empty."""
    value = (os.getenv(var) or '').strip()
    return Path(value) if value else default


# Pre-2024 legacy-format bhavcopy archive written once by ingestion/fetch_legacy_bhavcopy.py.
# Prod: /home/rakeshbk/myinvestiq/data/bhavcopy_legacy. Dev: point at prod's share (read-only).
LEGACY_BHAVCOPY_DIR = _dir_from_env('LEGACY_BHAVCOPY_DIR', REPO_ROOT / 'data' / 'bhavcopy_legacy')

# MyInvestIQ's UDiFF archive (2024-01-01 onward). READ-ONLY for this project. No default:
# this project must never silently read or create a local copy.
BHAVCOPY_ARCHIVE_DIR = _dir_from_env('BHAVCOPY_ARCHIVE_DIR')
INDEX_ARCHIVE_DIR = _dir_from_env('INDEX_ARCHIVE_DIR')

# This project's own UDiFF files for dates MyInvestIQ's archive does not hold (2024-01-03 to
# 2025-08-27, relocated 2026-10-08 by scripts/relocate_udiff_gap.py). Read-only after that.
# Prod: /home/rakeshbk/myinvestiq/data/strategy_trader/bhavcopy_udiff
UDIFF_GAP_DIR = _dir_from_env('UDIFF_GAP_DIR')
