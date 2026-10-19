"""Local-only role maintenance; never creates accounts or default passwords."""

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from capstone.core.settings import Settings
from capstone.db.models import User
from capstone.db.session import create_database_engine, write_transaction


def main() -> int:
    parser = argparse.ArgumentParser(description="本机管理员授权维护（先通过网页登录注册账号）")
    parser.add_argument("action", choices=["list", "grant", "revoke"])
    parser.add_argument("username", nargs="?")
    args = parser.parse_args()
    if args.action != "list" and not args.username:
        parser.error("grant / revoke 必须指定已有用户名")
    engine = create_database_engine(Settings().sqlite_path)
    try:
        with Session(engine) as session:
            if args.action == "list":
                for user in session.scalars(select(User).order_by(User.username)):
                    if args.username is None or user.username == args.username.strip().lower():
                        print(f"{user.username}\t{user.display_name}\t{user.role}")
            else:
                with write_transaction(session):
                    user = session.scalar(
                        select(User).where(User.username == args.username.strip().lower())
                    )
                    if user is None:
                        print("账号不存在，请先通过网页登录注册。")
                        return 1
                    user.role = "admin" if args.action == "grant" else "user"
                print(
                    f"{user.username} 的角色已设为 {user.role}；"
                    "原会话的下一次管理请求即按新角色校验。"
                )
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
