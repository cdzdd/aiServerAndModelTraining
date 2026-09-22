"""Local one-time admin bootstrap. Passwords are never command-line arguments."""

import argparse
import sys
import warnings
from getpass import GetPassWarning, getpass
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.config import Settings
from app.core.database import create_db_engine
from app.core.security import AuthError, password_hasher
from app.modules.auth.models import User
from app.modules.auth.schemas import RegisterInput
from app.modules.auth.service import active_admin_count, lock_admin_changes


def bootstrap(db: Session, data: RegisterInput) -> User:
    lock_admin_changes(db)
    if active_admin_count(db):
        raise AuthError(409, "ALREADY_INITIALIZED", "管理员已初始化")
    user = User(
        username=data.username,
        display_name=data.display_name,
        role="admin",
        password_hash=password_hasher.hash(data.password.get_secret_value()),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise AuthError(409, "CONFLICT", "用户名不可用；不会提升现有账号") from None
    record_audit(
        db,
        actor_id=user.id,
        action="auth.bootstrap",
        target_type="user",
        target_id=str(user.id),
        outcome="success",
        request_id=str(uuid4()),
        metadata={},
    )
    db.commit()
    return user


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default diagnostic repeats rejected arguments, which could contain a password.
        super().error("不支持此参数；密码只能通过隐藏提示或 --stdin-password 标准输入提供")


def main(argv=None) -> int:
    parser = SafeParser(description="初始化首个管理员")
    parser.add_argument(
        "--stdin-password", action="store_true", help="从标准输入读取一行密码；用户名仍通过提示输入"
    )
    args = parser.parse_args(argv)
    engine = create_db_engine(Settings())
    try:
        with Session(engine) as db:
            if active_admin_count(db):
                print("管理员已初始化")
                return 1
            db.rollback()
            username = input("用户名：")
            if args.stdin_password:
                password = sys.stdin.readline(131).rstrip("\r\n")
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", GetPassWarning)
                    password = getpass("密码（12–128 字符）：")
                    confirmation = getpass("再次输入密码：")
                if password != confirmation:
                    print("两次密码不一致")
                    return 1
            bootstrap(
                db, RegisterInput(username=username, password=password, display_name="管理员")
            )
            print("管理员初始化成功")
            return 0
    except AuthError as exc:
        print(exc.message)
        return 1
    except (ValidationError, EOFError, GetPassWarning):
        print("输入无效或无法安全隐藏密码；可使用 --stdin-password")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
