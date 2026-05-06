# 增强版基础智能体类
# 提供通用LLM调用功能，包含统计、缓存、重试、日志等功能

import json
import uuid
import os
import sys
import time
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional, Union
import requests
import random

# 可选：数据分析库
try:
    import pandas as pd
    import numpy as np
    HAS_ANALYTICS = True
except ImportError:
    HAS_ANALYTICS = False

# 可选：中文处理库
try:
    import jieba
    HAS_JIEBA = True
except ImportError:
    HAS_JIEBA = False

from ..utils.config import API_CONFIG, SYSTEM_CONFIG, CURRENT_API


class EnhancedBaseAgent:
    """增强版基础智能体类，提供通用LLM调用功能"""
    
    def __init__(self, name: str, config: Dict[str, Any] = None):
        self.name = name
        self.config = config or API_CONFIG
        self.model = self.config['model']
        self.temperature = self.config['temperature']
        self.max_tokens = self.config['max_tokens']
        self.api_key = self.config['api_key']
        self.base_url = self.config['base_url']
        
        # 增强的统计信息
        self.call_count = 0
        self.total_tokens = 0
        self.error_count = 0
        self.success_count = 0
        self.total_response_time = 0
        self.last_response_time = 0
        self.average_response_time = 0
        
        # 缓存机制
        self.response_cache = {}
        self.cache_enabled = True
        self.cache_hits = 0
        self.cache_misses = 0
        
        # 重试配置
        self.max_retries = SYSTEM_CONFIG.get('max_retries', 3)
        self.retry_delay = 1  # 初始重试延迟（秒）
        
        # 日志记录 - 必须在_init_client之前初始化
        self.logs = []
        self.log_level = SYSTEM_CONFIG.get('log_level', 'INFO')
        
        # 初始化API客户端
        self._init_client()
        
        self._log(f"智能体 {self.name} 初始化完成", "INFO")
    
    def _init_client(self):
        """初始化API客户端"""
        try:
            if CURRENT_API == "zhipuai":
                try:
                    from zhipuai import ZhipuAI
                    self.client = ZhipuAI(api_key=self.api_key)
                    self._log("智谱AI客户端初始化成功", "INFO")
                except ImportError:
                    self._log("zhipuai库未安装，请运行: pip install zhipuai", "ERROR")
                    self.client = None
            elif CURRENT_API == "openai":
                try:
                    import openai
                    openai.api_key = self.api_key
                    self.client = openai
                    self._log("OpenAI客户端初始化成功", "INFO")
                except ImportError:
                    self._log("openai库未安装，请运行: pip install openai", "ERROR")
                    self.client = None
            else:
                self.client = None
                self._log("自定义API需要手动实现", "WARNING")
        except Exception as e:
            self._log(f"导入API客户端失败: {e}", "ERROR")
            self.client = None
    
    def _log(self, message: str, level: str = "INFO"):
        """记录日志"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "agent": self.name,
            "message": message
        }
        self.logs.append(log_entry)
        
        # 控制台输出
        if level == "ERROR":
            print(f"❌ [{timestamp}] {self.name}: {message}")
        elif level == "WARNING":
            print(f"⚠️ [{timestamp}] {self.name}: {message}")
        elif level == "INFO":
            print(f"ℹ️ [{timestamp}] {self.name}: {message}")
        else:
            print(f"📝 [{timestamp}] {self.name}: {message}")
    
    def _generate_cache_key(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """生成缓存键"""
        cache_data = {
            "messages": messages,
            "model": self.model,
            "temperature": kwargs.get('temperature', self.temperature),
            "max_tokens": kwargs.get('max_tokens', self.max_tokens)
        }
        cache_string = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_string.encode()).hexdigest()
    
    def _get_from_cache(self, cache_key: str) -> Optional[str]:
        """从缓存获取响应"""
        if not self.cache_enabled:
            return None
        
        if cache_key in self.response_cache:
            self.cache_hits += 1
            self._log(f"缓存命中: {cache_key[:8]}...", "DEBUG")
            return self.response_cache[cache_key]
        
        self.cache_misses += 1
        return None
    
    def _save_to_cache(self, cache_key: str, response: str):
        """保存响应到缓存"""
        if not self.cache_enabled:
            return
        
        # 检查缓存大小限制
        cache_limit = SYSTEM_CONFIG.get('cache_size_limit', 100)
        if len(self.response_cache) >= cache_limit:
            # 删除最旧的缓存项
            oldest_key = next(iter(self.response_cache))
            del self.response_cache[oldest_key]
        
        self.response_cache[cache_key] = response
        self._log(f"响应已缓存: {cache_key[:8]}...", "DEBUG")
    
    def call_llm(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """调用大语言模型（增强版）"""
        start_time = time.time()
        self.call_count += 1
        
        # 生成缓存键
        cache_key = self._generate_cache_key(messages, **kwargs)
        
        # 尝试从缓存获取
        cached_response = self._get_from_cache(cache_key)
        if cached_response:
            self.last_response_time = time.time() - start_time
            self.total_response_time += self.last_response_time
            self.average_response_time = self.total_response_time / self.call_count
            return cached_response
        
        # 合并参数
        params = {
            'temperature': kwargs.get('temperature', self.temperature),
            'max_tokens': kwargs.get('max_tokens', self.max_tokens)
        }
        
        # 重试机制
        last_error = None
        for retry in range(self.max_retries):
            try:
                self._log(f"API调用开始 (尝试 {retry + 1}/{self.max_retries})", "DEBUG")
                
                if CURRENT_API == "zhipuai" and self.client:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        **params
                    )
                    content = response.choices[0].message.content
                elif CURRENT_API == "openai" and self.client:
                    response = self.client.ChatCompletion.create(
                        model=self.model,
                        messages=messages,
                        **params
                    )
                    content = response.choices[0].message.content
                else:
                    # 模拟API调用（用于测试）
                    content = self._mock_api_call(messages)
                
                # 计算响应时间
                self.last_response_time = time.time() - start_time
                self.total_response_time += self.last_response_time
                self.average_response_time = self.total_response_time / self.call_count
                
                # 统计token使用量（估算）
                estimated_tokens = len(str(messages)) + len(content)
                self.total_tokens += estimated_tokens
                
                # 成功计数
                self.success_count += 1
                
                # 保存到缓存
                self._save_to_cache(cache_key, content)
                
                self._log(f"API调用成功，响应时间: {self.last_response_time:.2f}s", "INFO")
                return content
                
            except Exception as e:
                last_error = e
                self.error_count += 1
                self._log(f"API调用失败 (尝试 {retry + 1}/{self.max_retries}): {e}", "ERROR")
                
                if retry < self.max_retries - 1:
                    # 指数退避
                    delay = self.retry_delay * (2 ** retry)
                    self._log(f"等待 {delay}s 后重试...", "INFO")
                    time.sleep(delay)
                else:
                    self._log(f"API调用最终失败: {e}", "ERROR")
        
        # 所有重试都失败，返回备用响应
        fallback_response = self._get_fallback_response(messages)
        self._save_to_cache(cache_key, fallback_response)
        return fallback_response
    
    def _mock_api_call(self, messages: List[Dict[str, str]]) -> str:
        """模拟API调用（用于测试）"""
        user_message = messages[-1]['content'] if messages else ""
        
        # 根据消息内容返回模拟响应
        if "标签" in user_message:
            return json.dumps({
                "recommended_tags": {
                    "类型标签": ["都市", "奇幻"],
                    "主题标签": ["成长", "冒险"],
                    "风格标签": ["轻松愉快"],
                    "受众标签": ["全年龄"]
                },
                "reasoning": "基于用户需求推荐",
                "confidence": 0.8
            }, ensure_ascii=False)
        elif "人物" in user_message:
            return json.dumps({
                "basic_info": {
                    "name": "张三",
                    "age": 25,
                    "gender": "男",
                    "occupation": "程序员"
                },
                "personality": {"description": "乐观开朗，善于思考"},
                "appearance": {"description": "中等身材，戴眼镜"},
                "background": {
                    "core_desire": "追求自由和冒险",
                    "fear": "害怕平凡",
                    "motivation": "改变现状"
                },
                "skills": ["编程", "逻辑思维"]
            }, ensure_ascii=False)
        else:
            return "这是一个模拟的API响应，请配置真实的API密钥。"
    
    def _get_fallback_response(self, messages: List[Dict[str, str]]) -> str:
        """获取备用响应"""
        self._log("使用备用响应", "WARNING")
        return self._mock_api_call(messages)
    
    def parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应并确保包含基本结构（增强版）"""
        if not response:
            self._log("收到空响应", "WARNING")
            return {
                "title": "解析错误",
                "content": "空响应",
                "error": "空响应"
            }
        
        # 尝试多种JSON提取方法
        json_patterns = [
            r'```json\s*(\{.*?\})\s*```',  # markdown代码块
            r'```\s*(\{.*?\})\s*```',      # 普通代码块
            r'(\{.*\})',                   # 直接JSON
        ]
        import re
        
        for pattern in json_patterns:
            matches = re.findall(pattern, response, re.DOTALL)
            if matches:
                try:
                    result = json.loads(matches[0])
                    self._log(f"JSON解析成功，使用模式: {pattern[:20]}...", "DEBUG")
                    return self._validate_json_structure(result)
                except json.JSONDecodeError as e:
                    self._log(f"JSON解析失败: {e}", "DEBUG")
                    continue
        
        # 如果都失败了，尝试直接解析
        try:
            result = json.loads(response)
            self._log("直接JSON解析成功", "DEBUG")
            return self._validate_json_structure(result)
        except json.JSONDecodeError:
            pass
        
        # 最后尝试提取第一个完整的JSON对象
        start = response.find('{')
        end = response.rfind('}') + 1
        if start != -1 and end > start:
            try:
                result = json.loads(response[start:end])
                self._log("提取JSON对象成功", "DEBUG")
                return self._validate_json_structure(result)
            except json.JSONDecodeError:
                pass
        
        # 如果仍然无法解析，返回带有默认结构的字典
        self._log("JSON解析完全失败，返回默认结构", "WARNING")
        return {
            "title": "解析失败的章节",
            "content": response[:500] + "..." if len(response) > 500 else response,
            "summary": "无法生成章节概要",
            "key_events": [],
            "foreshadowing": [],
            "error": "JSON解析失败"
        }
    
    def _validate_json_structure(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """验证和修复JSON结构"""
        # 确保包含基本结构
        if "content" in result:
            # 确保有标题
            if "title" not in result or not result["title"]:
                result["title"] = "未命名章节"
        
        # 添加时间戳
        result["generated_at"] = datetime.now().isoformat()
        
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """获取详细统计信息"""
        success_rate = (self.success_count / max(self.call_count, 1)) * 100
        cache_hit_rate = (self.cache_hits / max(self.cache_hits + self.cache_misses, 1)) * 100
        
        return {
            "name": self.name,
            "call_count": self.call_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "success_rate": round(success_rate, 2),
            "total_tokens": self.total_tokens,
            "total_response_time": round(self.total_response_time, 2),
            "average_response_time": round(self.average_response_time, 2),
            "last_response_time": round(self.last_response_time, 2),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": round(cache_hit_rate, 2),
            "cache_size": len(self.response_cache)
        }
    
    def reset_stats(self):
        """重置统计信息"""
        self.call_count = 0
        self.total_tokens = 0
        self.error_count = 0
        self.success_count = 0
        self.total_response_time = 0
        self.last_response_time = 0
        self.average_response_time = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self._log("统计信息已重置", "INFO")
    
    def clear_cache(self):
        """清空缓存"""
        cache_size = len(self.response_cache)
        self.response_cache.clear()
        self._log(f"已清空缓存，释放了 {cache_size} 个缓存项", "INFO")
    
    def get_logs(self, level: str = None) -> List[Dict[str, Any]]:
        """获取日志记录"""
        if level:
            return [log for log in self.logs if log["level"] == level]
        return self.logs
    
    def export_logs(self, filename: str = None) -> str:
        """导出日志到文件"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.name}_logs_{timestamp}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.logs, f, ensure_ascii=False, indent=2)
        
        self._log(f"日志已导出到: {filename}", "INFO")
        return filename
