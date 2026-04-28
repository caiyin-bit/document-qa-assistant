"""Seed (idempotent) the demo user for document QA assistant.

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

from argon2 import PasswordHasher
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.config import load_config
from src.db.session import make_engine
from src.models.schemas import User

# Default demo credentials. Convenience for dev/demo — login at
# /login with these works out of the box. Production deploys should
# either delete this user or change the password.
_DEMO_EMAIL = "demo@example.com"
_DEMO_PASSWORD = "demo"


async def main() -> None:
    cfg = load_config()
    engine = make_engine(cfg.db.url)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    raw = os.getenv("APP_USER_ID")
    target_id = UUID(raw) if raw else uuid4()

    async with sm() as s:
        existing = await s.get(User, target_id)
        if existing:
            # Backfill missing email + password_hash on a pre-auth-migration
            # demo user so the default `demo / demo` login works after
            # upgrading to the auth-enabled build.
            changed = False
            if not existing.email:
                existing.email = _DEMO_EMAIL
                changed = True
            if not existing.password_hash:
                existing.password_hash = PasswordHasher().hash(_DEMO_PASSWORD)
                changed = True
            if changed:
                await s.commit()
                print(
                    f"✅ Demo user existed, backfilled credentials: {existing.id}"
                )
            else:
                print(f"✅ Demo user already exists: {existing.id} (no-op)")
        else:
            u = User(
                id=target_id, name="demo",
                email=_DEMO_EMAIL,
                password_hash=PasswordHasher().hash(_DEMO_PASSWORD),
            )
            s.add(u)
            await s.commit()
            print(f"✅ Created demo user: {u.id}")
            if not raw:
                print(f"\n👉 Put this in .env:\n  APP_USER_ID={u.id}\n")
        print(f"   login at /login with: {_DEMO_EMAIL} / {_DEMO_PASSWORD}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
