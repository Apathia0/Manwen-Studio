# 增强版质量评估智能体
# 包含多维度质量评估、智能评分系统、改进建议生成、质量趋势分析

import json
from typing import Dict, List, Any, Optional
from datetime import datetime
import re

from ..core.base_agent import EnhancedBaseAgent


class EnhancedQualityAssessorAgent(EnhancedBaseAgent):
    """增强版质量评估智能体 - 多维度智能质量评估系统"""
    
    def __init__(self):
        super().__init__("增强质量评估智能体")
        
        # 质量评估维度
        self.assessment_dimensions = {
            "内容质量": {
                "权重": 0.3,
                "子维度": ["逻辑性", "创新性", "深度", "完整性"]
            },
            "文笔质量": {
                "权重": 0.25,
                "子维度": ["语言流畅度", "文采", "表达准确性", "风格一致性"]
            },
            "结构质量": {
                "权重": 0.2,
                "子维度": ["章节结构", "情节安排", "节奏控制", "伏笔设置"]
            },
            "人物质量": {
                "权重": 0.15,
                "子维度": ["人物立体性", "性格一致性", "成长弧线", "关系网络"]
            },
            "读者体验": {
                "权重": 0.1,
                "子维度": ["可读性", "吸引力", "情感共鸣", "记忆点"]
            }
        }
        
        # 评分标准
        self.scoring_criteria = {
            "优秀": {"分数范围": [90, 100], "描述": "达到出版标准，具有商业价值"},
            "良好": {"分数范围": [80, 89], "描述": "质量较高，有改进空间"},
            "一般": {"分数范围": [70, 79], "描述": "基本合格，需要改进"},
            "较差": {"分数范围": [60, 69], "描述": "存在明显问题，需要大幅改进"},
            "不合格": {"分数范围": [0, 59], "描述": "质量不达标，需要重新创作"}
        }
        
        self._log("增强版质量评估智能体初始化完成", "INFO")
    
    def assess_content_quality(self, content: str, content_type: str = "章节") -> Dict[str, Any]:
        """评估内容质量"""
        self._log(f"开始评估{content_type}质量", "INFO")
        
        # 基础质量检查
        basic_quality = self._basic_quality_check(content)
        
        # 深度质量分析
        deep_analysis = self._deep_quality_analysis(content, content_type)
        
        # 综合评分
        overall_score = self._calculate_overall_score(basic_quality, deep_analysis)
        
        # 生成改进建议
        improvement_suggestions = self._generate_improvement_suggestions(basic_quality, deep_analysis)
        
        result = {
            "content_type": content_type,
            "overall_score": overall_score,
            "quality_level": self._get_quality_level(overall_score),
            "dimension_scores": {
                "内容质量": basic_quality.get("content_score", 0),
                "文笔质量": basic_quality.get("writing_score", 0),
                "结构质量": basic_quality.get("structure_score", 0),
                "人物质量": deep_analysis.get("character_score", 0),
                "读者体验": deep_analysis.get("experience_score", 0)
            },
            "detailed_analysis": {
                "basic_quality": basic_quality,
                "deep_analysis": deep_analysis
            },
            "improvement_suggestions": improvement_suggestions,
            "assessment_time": datetime.now().isoformat()
        }
        
        self._log(f"{content_type}质量评估完成，总分: {overall_score}", "INFO")
        return result
    
    def _basic_quality_check(self, content: str) -> Dict[str, Any]:
        """基础质量检查"""
        analysis = {
            "content_score": 0,
            "writing_score": 0,
            "structure_score": 0,
            "issues": [],
            "strengths": []
        }
        
        # 内容质量检查
        if len(content) > 100:
            analysis["content_score"] += 20
            analysis["strengths"].append("内容长度适中")
        else:
            analysis["issues"].append("内容过短")
        
        # 文笔质量检查
        if self._check_language_fluency(content):
            analysis["writing_score"] += 25
            analysis["strengths"].append("语言流畅")
        else:
            analysis["issues"].append("语言不够流畅")
        
        # 结构质量检查
        if self._check_structure_quality(content):
            analysis["structure_score"] += 25
            analysis["strengths"].append("结构清晰")
        else:
            analysis["issues"].append("结构需要优化")
        
        return analysis
    
    def _deep_quality_analysis(self, content: str, content_type: str) -> Dict[str, Any]:
        """深度质量分析"""
        prompt = f"""
        请对以下{content_type}内容进行深度质量分析：
        内容：{content[:1000]}...
        
        请从以下维度进行评估：
        1. 内容质量：逻辑性、创新性、深度、完整性
        2. 文笔质量：语言流畅度、文采、表达准确性、风格一致性
        3. 结构质量：章节结构、情节安排、节奏控制、伏笔设置
        4. 人物质量：人物立体性、性格一致性、成长弧线、关系网络
        5. 读者体验：可读性、吸引力、情感共鸣、记忆点
        
        请返回JSON格式：
        {{
            "content_quality": {{
                "logic_score": 分数(0-100),
                "innovation_score": 分数(0-100),
                "depth_score": 分数(0-100),
                "completeness_score": 分数(0-100),
                "analysis": "详细分析"
            }},
            "writing_quality": {{
                "fluency_score": 分数(0-100),
                "literary_score": 分数(0-100),
                "accuracy_score": 分数(0-100),
                "consistency_score": 分数(0-100),
                "analysis": "详细分析"
            }},
            "structure_quality": {{
                "chapter_structure_score": 分数(0-100),
                "plot_arrangement_score": 分数(0-100),
                "rhythm_control_score": 分数(0-100),
                "foreshadowing_score": 分数(0-100),
                "analysis": "详细分析"
            }},
            "character_quality": {{
                "dimensionality_score": 分数(0-100),
                "consistency_score": 分数(0-100),
                "growth_arc_score": 分数(0-100),
                "relationship_score": 分数(0-100),
                "analysis": "详细分析"
            }},
            "reader_experience": {{
                "readability_score": 分数(0-100),
                "attractiveness_score": 分数(0-100),
                "emotional_resonance_score": 分数(0-100),
                "memorability_score": 分数(0-100),
                "analysis": "详细分析"
            }},
            "overall_analysis": "综合分析和建议"
        }}
        """
        
        messages = [
            {"role": "system", "content": "你是一个专业的小说质量评估专家，具有丰富的文学批评经验和出版行业背景。你能够从多个维度客观评估小说质量。"},
            {"role": "user", "content": prompt}
        ]
        
        response = self.call_llm(messages)
        result = self.parse_json_response(response)
        
        # 计算各维度得分
        dimension_scores = {}
        for dimension, data in result.items():
            if isinstance(data, dict) and "score" in str(data):
                scores = [v for k, v in data.items() if k.endswith("_score") and isinstance(v, (int, float))]
                if scores:
                    dimension_scores[dimension] = sum(scores) / len(scores)
        
        result["dimension_scores"] = dimension_scores
        return result
    
    def _calculate_overall_score(self, basic_quality: Dict[str, Any], deep_analysis: Dict[str, Any]) -> float:
        """计算综合得分"""
        # 基础质量得分
        basic_score = (
            basic_quality.get("content_score", 0) * 0.3 +
            basic_quality.get("writing_score", 0) * 0.35 +
            basic_quality.get("structure_score", 0) * 0.35
        )
        
        # 深度分析得分
        deep_scores = deep_analysis.get("dimension_scores", {})
        deep_score = sum(deep_scores.values()) / max(len(deep_scores), 1)
        
        # 综合得分（基础质量40%，深度分析60%）
        overall_score = basic_score * 0.4 + deep_score * 0.6
        return round(overall_score, 2)
    
    def _generate_improvement_suggestions(self, basic_quality: Dict[str, Any], deep_analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成改进建议"""
        suggestions = []
        
        # 基于基础质量问题的建议
        for issue in basic_quality.get("issues", []):
            if "内容过短" in issue:
                suggestions.append({
                    "type": "内容扩展",
                    "priority": "高",
                    "suggestion": "增加更多细节描述和情节发展",
                    "implementation": "可以添加环境描写、人物心理活动、对话细节等"
                })
            elif "语言不够流畅" in issue:
                suggestions.append({
                    "type": "文笔改进",
                    "priority": "高",
                    "suggestion": "优化语言表达，提高流畅度",
                    "implementation": "检查句式结构，避免重复用词，增加语言变化"
                })
            elif "结构需要优化" in issue:
                suggestions.append({
                    "type": "结构优化",
                    "priority": "中",
                    "suggestion": "重新组织内容结构",
                    "implementation": "确保逻辑清晰，段落安排合理，过渡自然"
                })
        
        # 基于深度分析的建议
        dimension_scores = deep_analysis.get("dimension_scores", {})
        for dimension, score in dimension_scores.items():
            if score < 70:
                suggestions.append({
                    "type": f"{dimension}提升",
                    "priority": "中",
                    "suggestion": f"提升{dimension}水平",
                    "implementation": f"针对{dimension}的具体问题进行改进"
                })
        
        return suggestions
    
    def _check_language_fluency(self, content: str) -> bool:
        """检查语言流畅度"""
        # 简单的流畅度检查
        sentences = re.split(r'[。！？]', content)
        if len(sentences) < 3:
            return False
        
        # 检查句子长度变化
        sentence_lengths = [len(s) for s in sentences if s.strip()]
        if len(sentence_lengths) < 2:
            return False
        
        # 检查是否有重复的词语
        words = content.split()
        if len(words) < 10:
            return False
        
        return True
    
    def _check_structure_quality(self, content: str) -> bool:
        """检查结构质量"""
        # 简单的结构检查
        if len(content) < 200:
            return False
        
        # 检查是否有段落分隔
        if '\n' not in content and '。' not in content:
            return False
        
        return True
    
    def _get_quality_level(self, score: float) -> str:
        """获取质量等级"""
        for level, criteria in self.scoring_criteria.items():
            min_score, max_score = criteria["分数范围"]
            if min_score <= score <= max_score:
                return level
        return "不合格"
    
    def assess_novel_overall_quality(self, novel_data: Dict[str, Any]) -> Dict[str, Any]:
        """评估整部小说的综合质量"""
        self._log("开始评估整部小说质量", "INFO")
        
        assessment_results = {
            "novel_id": novel_data.get("id", "unknown"),
            "assessment_time": datetime.now().isoformat(),
            "overall_quality": {},
            "chapter_quality": [],
            "character_quality": {},
            "storyline_quality": {},
            "improvement_plan": []
        }
        
        # 评估各章节质量
        chapters = novel_data.get("chapters", [])
        chapter_scores = []
        for chapter in chapters:
            chapter_content = chapter.get("content", "")
            if chapter_content:
                chapter_assessment = self.assess_content_quality(chapter_content, "章节")
                assessment_results["chapter_quality"].append({
                    "chapter_id": chapter.get("id", "unknown"),
                    "chapter_title": chapter.get("title", "未命名"),
                    "quality_score": chapter_assessment["overall_score"],
                    "quality_level": chapter_assessment["quality_level"]
                })
                chapter_scores.append(chapter_assessment["overall_score"])
        
        # 计算章节质量统计
        if chapter_scores:
            assessment_results["chapter_quality_stats"] = {
                "average_score": sum(chapter_scores) / len(chapter_scores),
                "highest_score": max(chapter_scores),
                "lowest_score": min(chapter_scores),
                "quality_consistency": max(chapter_scores) - min(chapter_scores)
            }
        
        # 评估人物质量
        characters = novel_data.get("characters", [])
        if characters:
            character_assessment = self._assess_character_quality(characters)
            assessment_results["character_quality"] = character_assessment
        
        # 评估故事线质量
        storyline = novel_data.get("storyline", {})
        if storyline:
            storyline_assessment = self._assess_storyline_quality(storyline)
            assessment_results["storyline_quality"] = storyline_assessment
        
        # 生成整体改进计划
        improvement_plan = self._generate_novel_improvement_plan(assessment_results)
        assessment_results["improvement_plan"] = improvement_plan
        
        self._log("整部小说质量评估完成", "INFO")
        return assessment_results
    
    def _assess_character_quality(self, characters: List[Dict[str, Any]]) -> Dict[str, Any]:
        """评估人物质量"""
        assessment = {
            "character_count": len(characters),
            "main_character_quality": 0,
            "supporting_character_quality": 0,
            "character_consistency": 0,
            "issues": [],
            "strengths": []
        }
        
        main_characters = [c for c in characters if c.get("character_type") == "主角"]
        supporting_characters = [c for c in characters if c.get("character_type") == "配角"]
        
        if main_characters:
            assessment["main_character_quality"] = 85  # 简化评分
            assessment["strengths"].append("主角设定完整")
        else:
            assessment["issues"].append("缺少主角设定")
        
        if supporting_characters:
            assessment["supporting_character_quality"] = 75  # 简化评分
            assessment["strengths"].append("配角设定丰富")
        else:
            assessment["issues"].append("配角设定不足")
        
        return assessment
    
    def _assess_storyline_quality(self, storyline: Dict[str, Any]) -> Dict[str, Any]:
        """评估故事线质量"""
        assessment = {
            "structure_completeness": 0,
            "plot_development": 0,
            "conflict_design": 0,
            "world_building": 0,
            "issues": [],
            "strengths": []
        }
        
        # 检查故事结构完整性
        if "three_act_structure" in storyline:
            three_act = storyline["three_act_structure"]
            if all(act in three_act for act in ["act1", "act2", "act3"]):
                assessment["structure_completeness"] = 90
                assessment["strengths"].append("故事结构完整")
            else:
                assessment["issues"].append("故事结构不完整")
        
        # 检查核心冲突
        if "main_conflict" in storyline:
            assessment["conflict_design"] = 80
            assessment["strengths"].append("核心冲突明确")
        else:
            assessment["issues"].append("核心冲突不明确")
        
        return assessment
    
    def _generate_novel_improvement_plan(self, assessment_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成整部小说的改进计划"""
        plan = []
        
        # 基于章节质量的改进建议
        chapter_stats = assessment_results.get("chapter_quality_stats", {})
        if chapter_stats:
            avg_score = chapter_stats.get("average_score", 0)
            if avg_score < 70:
                plan.append({
                    "priority": "高",
                    "area": "章节质量",
                    "action": "提升章节整体质量",
                    "target": f"将平均分从{avg_score}提升到80以上"
                })
        
        # 基于人物质量的改进建议
        character_quality = assessment_results.get("character_quality", {})
        if character_quality.get("issues"):
            plan.append({
                "priority": "中",
                "area": "人物设定",
                "action": "完善人物设定",
                "target": "解决人物设定中的问题"
            })
        
        return plan
    
    def generate_quality_report(self, assessment_results: Dict[str, Any]) -> str:
        """生成质量评估报告"""
        report = f"""
# 小说质量评估报告

## 📊 总体评估
- **评估时间**: {assessment_results.get('assessment_time', '未知')}
- **小说ID**: {assessment_results.get('novel_id', '未知')}

## 📖 章节质量分析
"""
        
        chapter_stats = assessment_results.get("chapter_quality_stats", {})
        if chapter_stats:
            report += f"""
- **平均质量得分**: {chapter_stats.get('average_score', 0):.1f}
- **最高得分**: {chapter_stats.get('highest_score', 0):.1f}
- **最低得分**: {chapter_stats.get('lowest_score', 0):.1f}
- **质量一致性**: {chapter_stats.get('quality_consistency', 0):.1f}
"""
        
        # 添加改进计划
        improvement_plan = assessment_results.get("improvement_plan", [])
        if improvement_plan:
            report += "\n## 🎯 改进计划\n"
            for i, item in enumerate(improvement_plan, 1):
                report += f"""
{i}. **{item['area']}** (优先级: {item['priority']})
   - 行动: {item['action']}
   - 目标: {item['target']}
"""
        
        return report
