#!/usr/bin/env python3
"""
手动执行数据库迁移脚本
用于修复 pro 分支同步后缺失的数据库列
"""
import sys
sys.path.insert(0, '.')

from database import engine
from sqlalchemy import text, inspect

def migrate():
    """执行缺失的数据库迁移"""
    insp = inspect(engine)
    changes_made = []

    print("[*] 检查数据库表结构...")

    # ── stories 表 ──────────────────────────────────────
    if "stories" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("stories")}
        with engine.begin() as conn:
            if "video_character_profiles" not in cols:
                conn.execute(text("ALTER TABLE stories ADD COLUMN video_character_profiles TEXT"))
                changes_made.append("[OK] stories.video_character_profiles")
                print("  [+] 添加 stories.video_character_profiles")
            else:
                print("  [SKIP] stories.video_character_profiles 已存在")

            if "video_style_preset_id" not in cols:
                # 先确保 video_style_presets 表存在
                if "video_style_presets" in insp.get_table_names():
                    conn.execute(text("ALTER TABLE stories ADD COLUMN video_style_preset_id INTEGER REFERENCES video_style_presets(id)"))
                    changes_made.append("[OK] stories.video_style_preset_id")
                    print("  [+] 添加 stories.video_style_preset_id")
                else:
                    print("  [WARN] 跳过 stories.video_style_preset_id（video_style_presets 表不存在）")
            else:
                print("  [SKIP] stories.video_style_preset_id 已存在")
    else:
        print("  [WARN] stories 表不存在")

    # ── chapters 表 ──────────────────────────────────────
    if "chapters" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("chapters")}
        with engine.begin() as conn:
            if "screenplay_text" not in cols:
                conn.execute(text("ALTER TABLE chapters ADD COLUMN screenplay_text TEXT"))
                changes_made.append("[OK] chapters.screenplay_text")
                print("  [+] 添加 chapters.screenplay_text")
            else:
                print("  [SKIP] chapters.screenplay_text 已存在")

            if "video_style_preset_id" not in cols:
                if "video_style_presets" in insp.get_table_names():
                    conn.execute(text("ALTER TABLE chapters ADD COLUMN video_style_preset_id INTEGER REFERENCES video_style_presets(id)"))
                    changes_made.append("[OK] chapters.video_style_preset_id")
                    print("  [+] 添加 chapters.video_style_preset_id")
                else:
                    print("  [WARN] 跳过 chapters.video_style_preset_id（video_style_presets 表不存在）")
            else:
                print("  [SKIP] chapters.video_style_preset_id 已存在")
    else:
        print("  [WARN] chapters 表不存在")

    # ── 总结 ──────────────────────────────────────
    print("\n" + "="*60)
    if changes_made:
        print(f"[SUCCESS] 迁移完成！共添加 {len(changes_made)} 个列：")
        for change in changes_made:
            print(f"   {change}")
    else:
        print("[SUCCESS] 所有列已存在，无需迁移")
    print("="*60)

if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"\n[ERROR] 迁移失败：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
