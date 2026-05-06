#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
InkAI 基本使用示例
==================

展示InkAI系统的基本使用方法。
"""

import sys
import os
import time

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inkai import LightweightInkAIWithContinuation


def example_create_urban_novel():
    """示例：创建都市系统小说"""
    print("📚 示例：创建都市系统小说")
    print("=" * 40)
    
    # 创建系统实例
    inkai = LightweightInkAIWithContinuation()
    
    # 创建都市系统文
    title = "程序员的逆袭之路"
    requirements = """
    我想写一个程序员获得系统后逆袭的故事：
    - 主角是25岁的程序员，性格内向但聪明
    - 意外获得一个编程系统，可以将代码技能应用到现实
    - 从普通程序员逐步成长为科技大佬
    - 风格轻松愉快，有成长和励志元素
    """
    
    print(f"📖 小说标题: {title}")
    print(f"📝 创作需求: {requirements.strip()}")
    print("\n🚀 开始创作...")
    
    # 创建小说
    novel_id = inkai.create_new_novel(title, requirements)
    
    if novel_id:
        print(f"✅ 小说创建成功！")
        print(f"📖 小说ID: {novel_id}")
        
        # 等待创作完成（简化版）
        print("⏳ 等待创作流程完成...")
        time.sleep(3)
        
        # 查看小说信息
        novel_info = inkai.get_novel_info(novel_id)
        if "error" not in novel_info:
            print(f"\n📊 小说信息:")
            print(f"  标题: {novel_info['title']}")
            print(f"  章节数: {novel_info['total_chapters']}")
            print(f"  创建时间: {novel_info['created_at']}")
        
        return novel_id
    else:
        print("❌ 小说创建失败")
        return None


def example_continue_novel(novel_id: str):
    """示例：续写小说"""
    print("\n🔄 示例：续写小说")
    print("=" * 40)
    
    # 创建系统实例
    inkai = LightweightInkAIWithContinuation()
    
    # 续写需求
    continuation_requirements = """
    希望在续写中：
    - 增加更多技术细节和编程场景
    - 展现主角的成长和能力提升
    - 加入一些人物互动和情感元素
    - 为后续情节埋下伏笔
    """
    
    print(f"📝 续写需求: {continuation_requirements.strip()}")
    print("\n✍️ 开始续写...")
    
    # 执行续写
    result = inkai.continue_novel(novel_id, continuation_requirements)
    
    if result.get("status") == "success":
        print("✅ 续写成功！")
        
        new_chapter = result["new_chapter"]
        analysis_summary = result["analysis_summary"]
        
        print(f"\n📝 新章节信息:")
        print(f"  标题: {new_chapter['title']}")
        print(f"  字数: {new_chapter['word_count']}")
        print(f"  创建时间: {new_chapter['created_at']}")
        
        print(f"\n📊 分析摘要:")
        print(f"  续写类型: {analysis_summary['continuation_type']}")
        print(f"  主要焦点: {analysis_summary['primary_focus']}")
        print(f"  连贯性得分: {analysis_summary['consistency_score']:.1f}")
        
        return True
    else:
        print(f"❌ 续写失败: {result.get('error', '未知错误')}")
        return False


def example_quality_assessment():
    """示例：质量评估"""
    print("\n📊 示例：质量评估")
    print("=" * 40)
    
    from inkai.agents.quality_assessor import EnhancedQualityAssessorAgent
    
    # 创建质量评估智能体
    assessor = EnhancedQualityAssessorAgent()
    
    # 示例章节内容
    sample_content = """
    第一章：平凡的开始
    
    林轩坐在办公室里，面对着屏幕上密密麻麻的代码，感觉头有些发晕。作为一名普通的程序员，
    他每天的工作就是修复bug、写新功能、参加无尽的会议。虽然工作稳定，但生活总是缺少一些
    什么。
    
    "又是一个普通的周五。"他自言自语道，伸了个懒腰。
    
    就在这时，电脑屏幕突然闪烁了一下，出现了一行奇怪的文字："系统正在激活..."
    
    林轩揉了揉眼睛，以为是自己看错了。但下一秒，一个半透明的界面出现在他面前，
    只有他能看见。
    
    "欢迎使用编程大师系统！"界面上显示着这样的文字。
    
    这一刻，林轩的人生即将发生翻天覆地的变化。
    """
    
    print("📝 评估示例章节...")
    
    # 执行质量评估
    assessment = assessor.assess_content_quality(sample_content, "章节")
    
    print(f"\n📊 评估结果:")
    print(f"  总体得分: {assessment['overall_score']}")
    print(f"  质量等级: {assessment['quality_level']}")
    
    print(f"\n📈 各维度得分:")
    for dimension, score in assessment['dimension_scores'].items():
        print(f"  {dimension}: {score}")
    
    print(f"\n💡 改进建议:")
    for suggestion in assessment['improvement_suggestions'][:3]:
        print(f"  - {suggestion.get('suggestion', 'N/A')}")
    
    return assessment


def example_advanced_features():
    """示例：高级功能"""
    print("\n🚀 示例：高级功能")
    print("=" * 40)
    
    from inkai.system.advanced_features import AdvancedFeaturesManager
    
    # 创建高级功能管理器
    advanced = AdvancedFeaturesManager()
    
    # 示例内容
    sample_story = "林轩是一个普通的程序员，直到他遇到了神秘的系统..."
    
    print("🎨 获取创意建议...")
    
    # 获取创意建议
    suggestions = advanced.get_creative_suggestions(
        content=sample_story,
        user_preferences={"style": "轻松", "theme": "科技"}
    )
    
    print(f"\n💡 创意建议:")
    if "plot_twists" in suggestions:
        twist = suggestions["plot_twists"]
        print(f"  情节转折类型: {twist.get('twist_type', 'N/A')}")
    
    if "emotion_enhancement" in suggestions:
        emotion = suggestions["emotion_enhancement"]
        print(f"  情感增强目标: {emotion.get('target_emotion', 'N/A')}")
    
    return suggestions


def main():
    """主函数"""
    print("🎯 InkAI 基本使用示例")
    print("=" * 50)
    print("版本: 2.0.0")
    print()
    
    try:
        # 示例1：创建都市系统小说
        novel_id = example_create_urban_novel()
        
        if novel_id:
            # 示例2：续写小说
            example_continue_novel(novel_id)
        
        # 示例3：质量评估
        example_quality_assessment()
        
        # 示例4：高级功能
        example_advanced_features()
        
        print("\n🎉 所有示例执行完成！")
        print("✨ 您现在可以开始使用InkAI进行创作了！")
        
    except Exception as e:
        print(f"❌ 示例执行出错: {e}")
        print("请检查系统配置和依赖安装")


if __name__ == "__main__":
    main()
