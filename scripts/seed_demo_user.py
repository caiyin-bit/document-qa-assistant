"""Seed (idempotent) the MVP demo broker user.

Behavior:
  - APP_USER_ID env set → use that UUID. If user exists, no-op + print.
    If missing, INSERT with that id + print.
  - APP_USER_ID NOT set → generate a fresh UUID, INSERT, print
    (legacy behavior for first-time host-mode setup).
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from src.config import load_config
from src.db.session import make_engine
from src.models.schemas import User


async def main() -> None:
    cfg = load_config()
    engine = make_engine(cfg.db.url)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    raw = os.getenv("APP_USER_ID")
    target_id = UUID(raw) if raw else uuid4()

    async with sm() as s:
        existing = await s.get(User, target_id)
        if existing:
            print(f"✅ Demo user already exists: {existing.id} (no-op)")
        else:
            u = User(id=target_id, name="demo broker")
            s.add(u)
            await s.commit()
            print(f"✅ Created demo user: {u.id}")
            if not raw:
                print(f"\n👉 Put this in .env:\n  APP_USER_ID={u.id}\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
