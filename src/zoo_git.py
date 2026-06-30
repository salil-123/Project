"""GitHub-backed zoo: data/catalogue/ is a git working tree of a shared zoo repo.

This is the "database" layer. catalogue.py writes cards as plain files (fast, offline);
this module is the explicit, separate step that versions and shares them. "Publish to the
zoo" = commit the changed cards + index and push to the remote — same git-backed model as
Hugging Face's card hub, which is why publishing, versioning and sharing all come for free.

Only the JSON cards + index.json live here; model .joblib artifacts stay outside this dir
(under data/refine, data/) so they're never committed — cards carry the metrics + provenance
that make a published card useful without the binary.

Configure the remote once via ZOO_REMOTE in .env (e.g. git@github.com:core-stack/lulc-zoo.git).
Without a remote, publish still commits locally (a perfectly good local history) and says so.
"""
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

import catalogue

load_dotenv()

REPO = catalogue.CATALOGUE_DIR
ARTIFACTS = REPO / "artifacts"
# the zoo holds the JSON cards + index + the PUBLISHED model binaries (#8). Training tables
# (.csv) and tiles (.npy) stay out; we keep the small joblibs under artifacts/ so a published
# model is actually usable by whoever pulls it, not just described.
GITIGNORE = ("# zoo = JSON cards + index + published model artifacts; nothing else\n"
             "*.csv\n*.npy\n*.joblib\n!artifacts/*.joblib\n")


def _git(*args, check=False):
    """Run git inside the catalogue dir; returns (returncode, combined_output)."""
    p = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)
    if check and p.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.returncode, (p.stdout + p.stderr).strip()


def remote_url():
    return os.getenv("ZOO_REMOTE")


def is_repo():
    return (REPO / ".git").exists()


def init_local():
    """Make data/catalogue a git repo on the configured remote (idempotent). Run at startup."""
    REPO.mkdir(parents=True, exist_ok=True)
    if not is_repo():
        _git("init")
        _git("checkout", "-b", "main")          # stable default branch name
    (REPO / ".gitignore").write_text(GITIGNORE)
    url = remote_url()
    if url:                                      # point 'origin' at the zoo (reset if changed)
        code, _ = _git("remote", "get-url", "origin")
        _git("remote", "set-url", "origin", url) if code == 0 else _git("remote", "add", "origin", url)
    return {"repo": str(REPO), "remote": url, "initialized": True}


def publish(card_ids=None, message=None, contributor=None, dataset_links=None):
    """Commit the changed cards (+ index) and push to the zoo. The publish action.

    card_ids: limit to specific cards; None = everything changed. Marks those model cards
    zoo.published=True (and stamps `contributor` if given, #6), stages their binaries (#8a), and
    records any public dataset links the user supplied (#8b) before committing. Pushes if a
    remote is set, else commits locally.
    """
    if not is_repo():
        init_local()

    published = _mark_published(card_ids, contributor=contributor)
    linked = _apply_dataset_links(dataset_links)
    if card_ids:
        paths = [str((catalogue._dir_for(c) / f"{c}.json").relative_to(REPO)) for c in card_ids]
        for c in card_ids:                                   # include each card's staged binary
            art = ARTIFACTS / f"{c}.joblib"
            if art.exists():
                paths.append(str(art.relative_to(REPO)))
        for ds in linked:                                    # and any dataset cards we linked
            paths.append(str((catalogue._dir_for(ds) / f"{ds}.json").relative_to(REPO)))
        _git("add", "index.json", *paths)
    else:
        _git("add", "-A")

    code, _ = _git("diff", "--cached", "--quiet")     # 1 => there are staged changes
    if code == 0:
        return {"committed": False, "pushed": False, "note": "nothing new to publish",
                "published_ids": published}
    msg = message or (f"publish {', '.join(card_ids)}" if card_ids else "publish zoo cards")
    _git("commit", "-m", msg, check=True)

    if not remote_url():
        return {"committed": True, "pushed": False, "published_ids": published,
                "note": "committed locally (no ZOO_REMOTE configured)"}
    code, out = _git("push", "-u", "origin", "main")
    return {"committed": True, "pushed": code == 0, "published_ids": published,
            "note": out if code else "pushed to origin/main"}


def _apply_dataset_links(dataset_links):
    """Record a public source link on each published dataset card (#8b): 'here's where this data
    was fetched from'. Only stored for datasets the user gave a link for — a private upload with
    no link simply keeps no link and its raw data never enters the zoo (cards/binaries only).
    Returns the dataset card ids that were updated, so publish can stage them."""
    updated = []
    for ds_id, url in (dataset_links or {}).items():
        url = (url or "").strip()
        if not url or not str(ds_id).startswith("ds_"):
            continue
        card = catalogue.get_card(ds_id)
        if not card:
            continue
        if card.get("source_url") != url:
            card["source_url"] = url
            card.setdefault("provenance", {})["source_url"] = url
            catalogue.write_card(card)
        updated.append(ds_id)
    return updated


def status():
    """What's local vs published: changed cards + ahead/behind the remote."""
    if not is_repo():
        return {"repo": False, "remote": remote_url()}
    _, porcelain = _git("status", "--porcelain", "-uall")   # list individual files, not dirs
    # porcelain is "XY <path>": drop the 2 status cols, then strip — robust to 1 or 2 status chars
    # (the old fixed ln[3:] slice was eating a path character).
    changed = [ln[2:].strip() for ln in porcelain.splitlines() if ln.strip()]
    _, ahead = _git("rev-list", "--count", "@{u}..HEAD")    # empty if no upstream yet
    # only count actual cards as "unpublished" — index.json is a derived file, not a card, so a
    # dirty index alone shouldn't read as "1 unpublished" (that confused the badge).
    cards = [c for c in changed if c.endswith(".json") and c.rsplit("/", 1)[-1] != "index.json"]
    return {"repo": True, "remote": remote_url(),
            "uncommitted": cards,
            "unpushed": int(ahead) if ahead.isdigit() else None}


def _mark_published(card_ids, contributor=None):
    """Prepare the model cards being published: flip zoo.published=True, stamp the contributor
    (#6), and copy each model's binary into the zoo's artifacts/ so the published model is
    actually shared, not just described (#8). Writes a card only when something changed, to
    avoid needless version bumps; the binary is refreshed every time (it may have been retrained)."""
    import shutil
    done = []
    ids = card_ids or [c["id"] for c in catalogue.list_cards(kind="model")]
    for cid in ids:
        if not cid.startswith("mc_"):
            continue
        card = catalogue.get_card(cid)
        if not card:
            continue
        zoo = card.setdefault("zoo", {})
        changed = False
        if not zoo.get("published"):
            zoo["published"] = True
            changed = True
        if contributor and zoo.get("contributor") != contributor:
            zoo["contributor"] = contributor
            changed = True
        # stage the model binary into the zoo (refresh each publish; record its path once)
        src = catalogue.ROOT / (card.get("artifact") or {}).get("path", "")
        if src.exists():
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, ARTIFACTS / f"{cid}.joblib")
            rel = f"artifacts/{cid}.joblib"
            if card.setdefault("artifact", {}).get("published_path") != rel:
                card["artifact"]["published_path"] = rel
                changed = True
        if changed:
            catalogue.write_card(card)
            done.append(cid)
    return done


if __name__ == "__main__":
    print("init:", init_local())
    print("status:", status())
