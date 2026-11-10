"""Copy users and projects from the old SQLite file into the Postgres that DATABASE_URL points at.

For the move to Postgres. The project folders under data/projects/ never move, only the rows that list
them, so once a row is copied its owner sees the project again exactly as it was.

    docker compose -f docker-compose.hub.yml exec lulc python scripts/import_sqlite.py
    docker compose -f docker-compose.hub.yml exec lulc python scripts/import_sqlite.py --dry-run

Safe to run more than once, and safe to run months later: a row already in Postgres (same email, same
project id) is left alone, never overwritten. The demo projects are the one special case: once they've
been set up again in Postgres, their old SQLite copies are skipped so the front page doesn't list two of each.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from sqlalchemy import create_engine, select  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402

SAMPLE_OWNER = "sample@local.dev"     # the owner the app seeds the demo projects under (backend.SAMPLE_OWNER)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="src", default=str(config.DATA_DIR / "corestack.db"),
                    help="the old SQLite file (default: data/corestack.db)")
    ap.add_argument("--dry-run", action="store_true", help="say what would be copied, copy nothing")
    args = ap.parse_args()

    if db.FELL_BACK:
        sys.exit("Postgres (DATABASE_URL) isn't answering, so there's nowhere to copy to; fix that first")
    if db._sqlite:
        sys.exit("DATABASE_URL isn't set to Postgres here, so there's nowhere to copy to")
    src_file = Path(args.src)
    if not src_file.exists():
        sys.exit(f"no SQLite file at {src_file}")

    db.init()                                       # the tables, if the app hasn't started on Postgres yet
    src = create_engine(f"sqlite:///{src_file.as_posix()}")
    users, projects = db.User.__table__, db.Project.__table__

    with src.connect() as old, db.engine.begin() as new:
        have_users = set(new.scalars(select(users.c.email)))
        have_projects = set(new.scalars(select(projects.c.id)))
        samples_here = bool(new.scalar(select(projects.c.id).where(projects.c.owner == SAMPLE_OWNER).limit(1)))

        new_users = [dict(r._mapping) for r in old.execute(select(users)) if r.email not in have_users]
        todo, skipped_samples = [], 0
        for r in old.execute(select(projects)):
            if r.id in have_projects:
                continue
            if r.owner == SAMPLE_OWNER and samples_here:     # the demos already got set up afresh
                skipped_samples += 1
                continue
            todo.append(dict(r._mapping))

        # a project whose folder is gone would show up and then fail to open, so leave it behind
        missing = [p for p in todo if not (config.DATA_DIR / "projects" / p["id"]).is_dir()]
        todo = [p for p in todo if p not in missing]

        print(f"users: {len(new_users)} to copy, {len(have_users)} already in Postgres")
        print(f"projects: {len(todo)} to copy, {len(have_projects)} already in Postgres, "
              f"{skipped_samples} old demo copies skipped, {len(missing)} without a folder skipped")
        for p in missing:
            print(f"  no folder for {p['id']} ({p['name']!r}, {p['owner']})")
        if args.dry_run:
            print("dry run: nothing copied")
            return
        if new_users:
            new.execute(users.insert(), new_users)
        if todo:
            new.execute(projects.insert(), todo)        # users first: a project points at its owner
        print("done")


if __name__ == "__main__":
    main()
