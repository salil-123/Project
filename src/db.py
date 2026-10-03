"""Users and projects, the only two things the app keeps in a database.

Same shape as Susmit's drone_docker (SQLAlchemy, a projects table owned by a user, a JSON history of
runs on the row) so the two services read alike on the tower. Where we differ is the store: the
cluster checklist wants its central Postgres (#9), so DATABASE_URL points there; a SQLite file under
data/ is only the laptop fallback when DATABASE_URL is unset.

Everything bulky (hierarchy, examples, weights, GeoTIFFs) lives in the project's folder, not here.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

import config


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)   # naive UTC, same in Postgres and SQLite


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    picture: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_login: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:12])
    owner: Mapped[str] = mapped_column(ForeignKey("users.email"), index=True)
    name: Mapped[str] = mapped_column(String, default="")
    bbox: Mapped[list] = mapped_column(JSON)                  # [west, south, east, north]
    year: Mapped[int] = mapped_column(Integer, default=2024)
    base_scheme: Mapped[str] = mapped_column(String, default="indiasat")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # 0 = never run. Each run gets run_<n>/ on disk; `runs` is the light history the list shows
    current_run: Mapped[int] = mapped_column(Integer, default=0)
    runs: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


_sqlite = config.DATABASE_URL.startswith("sqlite")
# the checklist's spelling is postgresql://..., and which driver that means depends on the SQLAlchemy
# version (2.1 switched the default from psycopg2 to psycopg 3). Name it, so an upgrade can't break it.
_url = config.DATABASE_URL
for _plain in ("postgresql://", "postgres://"):
    if _url.startswith(_plain):
        _url = "postgresql+psycopg://" + _url[len(_plain):]
engine = create_engine(_url, future=True,
                       connect_args={"check_same_thread": False, "timeout": 30} if _sqlite else {})
Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

if _sqlite:
    @event.listens_for(engine, "connect")
    def _wal(conn, _rec):
        # WAL so a status poll never trips over a write, the same fix Susmit needed
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


def init():
    """Create the tables if they're missing. Fine for two tables; Alembic once they start changing."""
    if _sqlite:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def project_dict(p: Project) -> dict:
    return {"id": p.id, "owner": p.owner, "name": p.name, "bbox": p.bbox, "year": p.year,
            "base_scheme": p.base_scheme, "is_public": p.is_public,
            "current_run": p.current_run, "runs": p.runs or [],
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None}
