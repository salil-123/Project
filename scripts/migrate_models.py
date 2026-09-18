"""Move trained weights out of data/ and into models/ (cluster checklist #1).

The checklist wants three separate host mounts -- code/ -> /app, models/ -> /app/models,
data/ -> /app/data -- with weights under models/ rather than data/ or the image. Historically ours
lived in data/refine/ and data/model_*.joblib, and that spelling is baked into every zoo card's
`artifact.path`, which is data we'd rather not rewrite.

So the code resolves weights through config.model_path(), which checks models/ first and falls back
to the old data/ home. This script does the actual move; until you run it nothing breaks, and after
you run it nothing breaks either.

    python scripts/migrate_models.py --dry-run     # show what would move
    python scripts/migrate_models.py               # move it

Copies rather than deletes when --keep is passed, in case you want to roll back by hand.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config

# (source under data/, destination tail under models/)
TARGETS = [("refine", "refine")] + [(f"{n}.joblib", f"{n}.joblib") for n in
                                    ("model_pooled", "model_softvote", "model_softvote_reconciled",
                                     "model_worldcover_base")]


def migrate(dry_run: bool = False, keep: bool = False) -> int:
    src_root, dst_root = config.DATA_DIR, config.MODELS_DIR
    moved = skipped = 0

    for src_tail, dst_tail in TARGETS:
        src, dst = src_root / src_tail, dst_root / dst_tail
        if not src.exists():
            continue
        # weights only: data/refine/ also holds sampled *_train.csv tables, which are regenerable
        # DATA and stay where they are (checklist #1 splits models from data).
        files = ([f for f in src.rglob("*.joblib") if f.is_file()] if src.is_dir() else [src])
        for f in files:
            rel = f.relative_to(src) if src.is_dir() else Path(f.name)
            target = (dst / rel) if src.is_dir() else dst
            if target.exists():
                skipped += 1
                continue
            mb = f.stat().st_size / 1e6
            print(f"  {'would move' if dry_run else 'move'} {f.relative_to(ROOT)} -> "
                  f"{target.relative_to(ROOT)}  ({mb:.1f} MB)")
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
                if not keep:
                    f.unlink()
            moved += 1

    print(f"\n{'would move' if dry_run else 'moved'} {moved} file(s), {skipped} already in models/")
    if moved and not dry_run:
        print(f"weights now under {dst_root}")
        print("cards still say data/refine/... — config.model_path() resolves that to models/.")
    return 0


if __name__ == "__main__":
    sys.exit(migrate(dry_run="--dry-run" in sys.argv, keep="--keep" in sys.argv))
