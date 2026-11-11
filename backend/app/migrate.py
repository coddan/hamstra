from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .db import engine

BASELINE = "0001"


def run_migrations() -> None:
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        tables = set(inspect(conn).get_table_names())
        if "alembic_version" not in tables and "movies" in tables:
            command.stamp(cfg, BASELINE)  # database created before migrations existed
        command.upgrade(cfg, "head")
