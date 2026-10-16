# -*- coding: utf-8 -*-
"""ST-012: migration discovery and planning (no database). The SQL itself is proven on prod (check_database)."""

import pytest

from scripts.migrate import MIGRATIONS_DIR, discover, plan


def write(folder, name, text='SELECT 1;'):
    (folder / name).write_text(text, encoding='utf-8')


def test_discover_sorts_and_hashes(tmp_path):
    write(tmp_path, '002_second.sql', 'SELECT 2;')
    write(tmp_path, '001_first.sql', 'SELECT 1;')
    files = discover(tmp_path)
    assert [(v, n) for v, n, _, _ in files] == [(1, '001_first.sql'), (2, '002_second.sql')]
    assert files[0][2] != files[1][2] and len(files[0][2]) == 64


@pytest.mark.parametrize('bad', ['1_first.sql', '001-first.sql', '001_First.sql'])
def test_discover_refuses_bad_names(tmp_path, bad):
    write(tmp_path, bad)
    with pytest.raises(ValueError):
        discover(tmp_path)


def test_discover_refuses_duplicate_versions(tmp_path):
    write(tmp_path, '001_a.sql')
    write(tmp_path, '001_b.sql')
    with pytest.raises(ValueError):
        discover(tmp_path)


def test_plan_skips_applied_and_refuses_changed_or_missing(tmp_path):
    write(tmp_path, '001_first.sql')
    write(tmp_path, '002_second.sql', 'SELECT 2;')
    files = discover(tmp_path)
    sha1 = files[0][2]
    assert [v for v, *_ in plan(files, {})] == [1, 2]
    assert [v for v, *_ in plan(files, {1: ('001_first.sql', sha1)})] == [2]
    assert plan(files, {1: ('001_first.sql', sha1), 2: ('002_second.sql', files[1][2])}) == []
    with pytest.raises(ValueError, match='changed'):
        plan(files, {1: ('001_first.sql', 'other')})
    with pytest.raises(ValueError, match='missing'):
        plan(files, {3: ('003_gone.sql', 'x')})


def test_repo_migrations_are_well_formed():
    """The real folder: 001 present, and it creates all 14 tables of the approved model."""
    files = discover(MIGRATIONS_DIR)
    assert files[0][:2] == (1, '001_initial_schema.sql')
    sql = files[0][3]
    for t in ['strategies', 'models', 'signals', 'proposals', 'positions', 'orders', 'order_charges', 'gtt_orders',
              'position_adjustments', 'order_events', 'guardrail_events', 'daily_snapshots', 'reconciliations',
              'audit_log']:
        assert f'CREATE TABLE {t} (' in sql, t
