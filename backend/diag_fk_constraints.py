"""诊断脚本：查询数据库中指向 stories / chapters 的真实外键约束与 delete_rule。

只读查询，不修改任何数据。用法：python diag_fk_constraints.py
"""
import sys

from sqlalchemy import create_engine, text

import database

engine = create_engine(database.DATABASE_URL)

FK_SQL = text("""
SELECT tc.table_name,
       kcu.column_name,
       ccu.table_name AS ref_table,
       rc.delete_rule
FROM information_schema.referential_constraints rc
JOIN information_schema.table_constraints tc
     ON tc.constraint_name = rc.constraint_name
     AND tc.constraint_schema = rc.constraint_schema
JOIN information_schema.key_column_usage kcu
     ON kcu.constraint_name = rc.constraint_name
     AND kcu.constraint_schema = rc.constraint_schema
JOIN information_schema.constraint_column_usage ccu
     ON ccu.constraint_name = rc.unique_constraint_name
     AND ccu.constraint_schema = rc.constraint_schema
WHERE ccu.table_name IN ('stories', 'chapters')
ORDER BY ccu.table_name, tc.table_name, kcu.column_name
""")


def main():
    with engine.connect() as conn:
        rows = conn.execute(FK_SQL).fetchall()
    grouped = {}
    for table, column, ref_table, delete_rule in rows:
        grouped.setdefault(ref_table, []).append((table, column, delete_rule))
    for ref_table in ("stories", "chapters"):
        print(f"\n=== 指向 {ref_table}.id 的外键 ===")
        if ref_table not in grouped:
            print("  （无）")
            continue
        for table, column, rule in grouped[ref_table]:
            flag = "  <-- 无 CASCADE" if rule != "CASCADE" else ""
            print(f"  {table:30s} {column:20s} {rule}{flag}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - 诊断脚本，输出原始错误即可
        print(f"诊断失败: {exc}", file=sys.stderr)
        sys.exit(1)
