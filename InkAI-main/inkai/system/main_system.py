# 轻量级续写系统集成
# 将续写功能整合到现有系统中

import json
import time
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

from ..agents.tag_selector import EnhancedTagSelectorAgent
from ..agents.character_creator import EnhancedCharacterCreatorAgent
from ..agents.storyline_generator import EnhancedStorylineGeneratorAgent
from ..agents.chapter_writer import EnhancedChapterWriterAgent
from ..agents.quality_assessor import EnhancedQualityAssessorAgent
from ..agents.continuation_analyzer import ContinuationAnalyzerAgent
from ..agents.continuation_writer import ContinuationWriterAgent
from ..managers.data_manager import EnhancedDataManager
from ..managers.workflow_controller import EnhancedWorkflowController


class LightweightInkAIWithContinuation:
    """带续写功能的轻量级InkAI系统"""
    
    def __init__(self):
        # 初始化原有智能体
        self.tag_selector = EnhancedTagSelectorAgent()
        self.character_creator = EnhancedCharacterCreatorAgent()
        self.storyline_generator = EnhancedStorylineGeneratorAgent()
        self.chapter_writer = EnhancedChapterWriterAgent()
        self.quality_assessor = EnhancedQualityAssessorAgent()
        self.data_manager = EnhancedDataManager()
        self.workflow_controller = EnhancedWorkflowController()
        
        # 初始化续写智能体
        self.continuation_analyzer = ContinuationAnalyzerAgent()
        self.continuation_writer = ContinuationWriterAgent()
        
        # 注册所有智能体到工作流程控制器
        self._register_all_agents()
        
        self.current_novel_id = None
        self.current_data = {}
        
        print("✅ 轻量级InkAI系统（含续写功能）初始化完成")
    
    def _register_all_agents(self):
        """注册所有智能体"""
        agents_to_register = [
            ("tag_selector", self.tag_selector, ["标签推荐"]),
            ("character_creator", self.character_creator, ["人物创建"]),
            ("storyline_generator", self.storyline_generator, ["故事线生成"]),
            ("chapter_writer", self.chapter_writer, ["章节写作"]),
            ("quality_assessor", self.quality_assessor, ["质量评估"]),
            ("continuation_analyzer", self.continuation_analyzer, ["续写分析"]),
            ("continuation_writer", self.continuation_writer, ["续写写作"])
        ]
        
        for agent_name, agent_instance, capabilities in agents_to_register:
            self.workflow_controller.register_agent(agent_name, agent_instance, capabilities)
    
    def create_new_novel(self, title: str, requirements: str) -> str:
        """创建新小说（原有功能）"""
        print(f"📚 开始创建新小说: {title}")
        
        # 使用原有的创建流程
        project_data = {
            "title": title,
            "description": requirements,
            "created_at": datetime.now().isoformat()
        }
        
        project_id = self.data_manager.create_novel_project(project_data)
        
        # 创建工作流程
        workflow_id = self.workflow_controller.create_workflow("novel_creation", project_id, {
            "user_requirements": requirements,
            "target_length": 100000,
            "style_preference": "网络小说"
        })
        
        # 启动工作流程
        success = self.workflow_controller.start_workflow(workflow_id)
        if success:
            print("✅ 新小说创作工作流程启动成功！")
            self.current_novel_id = project_id
            return project_id
        else:
            print("❌ 新小说创作工作流程启动失败")
            return ""
    
    def continue_novel(self, novel_id: str, continuation_requirements: str = "") -> Dict[str, Any]:
        """续写小说（新功能）"""
        print(f"🔄 开始续写小说: {novel_id}")
        
        # 加载小说数据
        novel_data = self.data_manager.load_novel_project(novel_id)
        if not novel_data:
            return {"error": "小说不存在"}
        
        try:
            # 执行续写分析
            print("📊 分析现有内容...")
            analysis_result = self.continuation_analyzer.analyze_for_continuation(novel_data, continuation_requirements)
            
            # 执行续写写作
            print("✍️ 执行续写...")
            continuation_result = self.continuation_writer.write_continuation(novel_data, analysis_result, continuation_requirements)
            
            # 保存续写结果
            print("💾 保存续写结果...")
            self._save_continuation(novel_id, continuation_result)
            
            return {
                "status": "success",
                "novel_id": novel_id,
                "new_chapter": continuation_result["chapter_info"],
                "analysis_summary": {
                    "continuation_type": analysis_result["continuation_direction"]["continuation_type"],
                    "primary_focus": analysis_result["continuation_direction"]["primary_focus"],
                    "consistency_score": continuation_result["consistency_check"]["overall_score"]
                }
            }
        except Exception as e:
            print(f"❌ 续写过程出错: {e}")
            return {"error": f"续写失败: {str(e)}"}
    
    def _save_continuation(self, novel_id: str, continuation_result: Dict[str, Any]):
        """保存续写结果"""
        # 加载现有数据
        novel_data = self.data_manager.load_novel_project(novel_id)
        if not novel_data:
            return
        
        # 添加新章节
        new_chapter = {
            "id": str(uuid.uuid4()),
            "title": continuation_result["chapter_info"]["title"],
            "content": continuation_result["content"]["content"],
            "summary": continuation_result["content"]["summary"],
            "key_events": continuation_result["content"]["key_events"],
            "foreshadowing": continuation_result["content"]["foreshadowing"],
            "created_at": continuation_result["chapter_info"]["created_at"],
            "word_count": continuation_result["chapter_info"]["word_count"]
        }
        
        # 更新章节列表
        if "chapters" not in novel_data:
            novel_data["chapters"] = []
        novel_data["chapters"].append(new_chapter)
        
        # 更新元数据
        novel_data["updated_at"] = datetime.now().isoformat()
        novel_data["total_chapters"] = len(novel_data["chapters"])
        
        # 保存数据
        self.data_manager.save_novel_project(novel_id, novel_data)
    
    def get_novel_info(self, novel_id: str) -> Dict[str, Any]:
        """获取小说信息"""
        novel_data = self.data_manager.load_novel_project(novel_id)
        if not novel_data:
            return {"error": "小说不存在"}
        
        return {
            "novel_id": novel_id,
            "title": novel_data.get("title", "未命名小说"),
            "total_chapters": len(novel_data.get("chapters", [])),
            "created_at": novel_data.get("created_at", ""),
            "updated_at": novel_data.get("updated_at", ""),
            "last_chapter": novel_data.get("chapters", [])[-1] if novel_data.get("chapters") else None
        }
    
    def list_novels(self) -> List[Dict[str, Any]]:
        """列出所有小说"""
        novels = []
        project_list = self.data_manager.list_novel_projects()
        
        for project_id in project_list:
            novel_info = self.get_novel_info(project_id)
            if "error" not in novel_info:
                novels.append(novel_info)
        
        return novels
    
    def export_novel(self, novel_id: str, format_type: str = "txt") -> str:
        """导出小说"""
        novel_data = self.data_manager.load_novel_project(novel_id)
        if not novel_data:
            return "导出失败：小说不存在"
        
        if format_type == "txt":
            content = f"《{novel_data['title']}》\n"
            content += "=" * len(novel_data['title']) + "\n\n"
            
            for i, chapter in enumerate(novel_data.get("chapters", [])):
                title = chapter.get("title", f"第{i+1}章")
                chapter_content = chapter.get("content", "内容缺失")
                
                content += f"{title}\n"
                content += "-" * len(title) + "\n"
                content += chapter_content + "\n\n"
            
            # 保存为txt文件
            filename = f"{novel_data['title']}.txt"
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(content)
                return filename
            except Exception as e:
                print(f"导出失败: {e}")
                return ""
        
        return ""
    
    def get_system_stats(self) -> Dict[str, Any]:
        """获取系统统计信息"""
        # 获取各智能体统计
        agents_stats = {
            "tag_selector": self.tag_selector.get_stats(),
            "character_creator": self.character_creator.get_stats(),
            "storyline_generator": self.storyline_generator.get_stats(),
            "chapter_writer": self.chapter_writer.get_stats(),
            "quality_assessor": self.quality_assessor.get_stats(),
            "continuation_analyzer": self.continuation_analyzer.get_stats(),
            "continuation_writer": self.continuation_writer.get_stats()
        }
        
        # 获取数据管理统计
        data_stats = self.data_manager.get_statistics()
        
        # 获取工作流程统计
        workflow_stats = self.workflow_controller.get_performance_metrics()
        
        return {
            "agents_stats": agents_stats,
            "data_stats": data_stats,
            "workflow_stats": workflow_stats,
            "system_status": "运行中"
        }
    
    def shutdown(self):
        """关闭系统"""
        print("🔄 正在关闭InkAI系统...")
        
        # 关闭工作流程控制器
        self.workflow_controller.shutdown()
        
        print("✅ InkAI系统已关闭")
