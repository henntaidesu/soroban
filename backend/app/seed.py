"""Create the dev admin account. Run: python -m app.seed

不开放注册；开发期用这个脚本建一个 admin。可用环境变量覆盖默认账号密码：
  SOROBAN_ADMIN_USER (默认 admin)
  SOROBAN_ADMIN_PASS (默认 admin123)
"""

import os

from sqlmodel import Session, select

from .auth import hash_password
from .database import create_db_and_tables, engine
from .models import User


def main() -> None:
    create_db_and_tables()
    username = os.getenv("SOROBAN_ADMIN_USER", "admin")
    password = os.getenv("SOROBAN_ADMIN_PASS", "admin123")

    with Session(engine) as session:
        existing = session.exec(select(User).where(User.username == username)).first()
        if existing:
            print(f"用户 {username!r} 已存在，跳过。")
            return
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name="管理员",
        )
        session.add(user)
        session.commit()
        print(f"已创建 admin：{username} / {password}（请尽快改密码/改环境变量）")


if __name__ == "__main__":
    main()
