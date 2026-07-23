#!/usr/bin/env python3
"""手动执行完整数据库初始化和增量迁移。"""

import sys
import traceback

from database import init_db


def migrate() -> None:
    print("[*] 开始执行完整数据库迁移...")
    init_db(run_migrations=True, raise_errors=True)
    print("[SUCCESS] 数据库迁移完成")


if __name__ == "__main__":
    try:
        migrate()
    except Exception as exc:
        print(f"[ERROR] 数据库迁移失败：{exc}")
        traceback.print_exc()
        sys.exit(1)
