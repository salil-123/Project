"""Refresh data/catalogue_seed/ from the live zoo at data/catalogue/.

Why this exists: data/catalogue is gitignored (the zoo is its own git repo), so a fresh clone of
*this* repo starts with no cards and the app falls back to whatever backfill() can regenerate -- the
"only 4 models on the live site" bug. The seed is the version-controlled copy that rides along with a
plain `git pull`; catalogue.seed_from_bundled() copies it into place on startup.

Run this after training/publishing something you want deployments to see, then commit the seed:

    python scripts/sync_catalogue_seed.py
    git add data/catalogue_seed && git commit -m "zoo: refresh seed"

Artifacts over MAX_ARTIFACT_MB are skipped -- the biomass forest is 528 MB, way past GitHub's limit.
Its *card* still ships, so the zoo lists it; the binary comes from deploy/fetch_models.sh.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "data" / "catalogue"
SEED = ROOT / "data" / "catalogue_seed"
SUBDIRS = ("models", "datasets", "artifacts")
MAX_ARTIFACT_MB = 50


def sync(prune: bool = True) -> int:
    if not LIVE.exists():
        print(f"no live catalogue at {LIVE} -- nothing to sync")
        return 1

    copied = skipped = removed = 0
    for sub in SUBDIRS:
        src_dir, dst_dir = LIVE / sub, SEED / sub
        dst_dir.mkdir(parents=True, exist_ok=True)
        keep = set()

        for f in sorted(src_dir.iterdir()) if src_dir.exists() else []:
            if not f.is_file():
                continue
            mb = f.stat().st_size / 1e6
            if mb > MAX_ARTIFACT_MB:
                print(f"  skip  {sub}/{f.name}  ({mb:.0f} MB > {MAX_ARTIFACT_MB} MB cap)")
                skipped += 1
                continue
            keep.add(f.name)
            dst = dst_dir / f.name
            # only rewrite what actually changed, so git doesn't see churn on every run
            if not dst.exists() or dst.read_bytes() != f.read_bytes():
                shutil.copy2(f, dst)
                copied += 1

        # drop seed files the live zoo no longer has, else deleted cards haunt every deploy
        if prune:
            for f in sorted(dst_dir.iterdir()):
                if f.is_file() and f.name not in keep:
                    f.unlink()
                    print(f"  prune {sub}/{f.name}")
                    removed += 1

    # index.json is deliberately NOT seeded -- seed_from_bundled() rebuilds it after copying, so it
    # always describes what actually landed on that box rather than what was on ours.
    print(f"\nseed at {SEED}: {copied} copied, {removed} pruned, {skipped} too big")
    for sub in SUBDIRS:
        print(f"  {sub}: {len(list((SEED / sub).iterdir()))}")
    return 0


if __name__ == "__main__":
    sys.exit(sync(prune="--no-prune" not in sys.argv))
