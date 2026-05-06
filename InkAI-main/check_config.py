#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
InkAI 配置检查工具
==================

检查系统配置和依赖是否正确安装。
"""

import sys
import os

def check_python_version():
    """检查Python版本"""
    print("🐍 检查Python版本...")
    
    version = sys.version_info
    if version.major == 3 and version.minor >= 8:
        print(f"✅ Python版本: {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print(f"❌ Python版本过低: {version.major}.{version.minor}.{version.micro}")
        print("   需要Python 3.8或更高版本")
        return False

def check_dependencies():
    """检查依赖包"""
    print("\n📦 检查依赖包...")
    
    required_packages = [
        "zhipuai",
        "requests", 
        "python-dateutil"
    ]
    
    optional_packages = [
        "pandas",
        "numpy", 
        "jieba",
        "flask",
        "cachetools",
        "psutil"
    ]
    
    missing_required = []
    missing_optional = []
    
    # 检查必需包
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} (必需)")
            missing_required.append(package)
    
    # 检查可选包
    for package in optional_packages:
        try:
            __import__(package.replace("-", "_"))
            print(f"✅ {package} (可选)")
        except ImportError:
            print(f"⚠️ {package} (可选)")
            missing_optional.append(package)
    
    if missing_required:
        print(f"\n❌ 缺少必需依赖: {', '.join(missing_required)}")
        print("请运行: pip install -r requirements.txt")
        return False
    
    if missing_optional:
        print(f"\n⚠️ 缺少可选依赖: {', '.join(missing_optional)}")
        print("可运行: pip install -e .[full] 安装完整功能")
    
    return True

def check_api_config():
    """检查API配置"""
    print("\n🔑 检查API配置...")
    
    try:
        # 添加项目路径
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        
        from inkai.utils.config import API_CONFIG, CURRENT_API
        
        print(f"✅ 当前API提供商: {CURRENT_API}")
        
        api_key = API_CONFIG.get("api_key", "")
        if api_key and api_key != "your_api_key_here":
            print("✅ API密钥已配置")
        else:
            print("⚠️ API密钥未配置，将使用模拟模式")
            print("   请在 inkai/utils/config.py 中设置API密钥")
        
        print(f"✅ API模型: {API_CONFIG.get('model', '未知')}")
        print(f"✅ API基础URL: {API_CONFIG.get('base_url', '未知')}")
        
        return True
        
    except Exception as e:
        print(f"❌ API配置检查失败: {e}")
        return False

def check_directories():
    """检查目录结构"""
    print("\n📁 检查目录结构...")
    
    required_dirs = [
        "inkai",
        "inkai/core",
        "inkai/agents", 
        "inkai/managers",
        "inkai/system",
        "inkai/utils"
    ]
    
    for dir_path in required_dirs:
        if os.path.exists(dir_path):
            print(f"✅ {dir_path}")
        else:
            print(f"❌ {dir_path}")
            return False
    
    # 检查关键文件
    required_files = [
        "main.py",
        "setup.py",
        "requirements.txt",
        "inkai/__init__.py",
        "inkai/core/base_agent.py"
    ]
    
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path}")
            return False
    
    return True

def check_system_ready():
    """检查系统是否准备就绪"""
    print("\n🎯 系统就绪检查...")
    
    try:
        # 尝试导入主系统
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from inkai import LightweightInkAIWithContinuation
        
        print("✅ 主系统导入成功")
        
        # 检查是否可以创建实例（不实际创建，避免初始化开销）
        print("✅ 系统类可用")
        
        return True
        
    except Exception as e:
        print(f"❌ 系统就绪检查失败: {e}")
        return False

def main():
    """主函数"""
    print("🔧 InkAI 配置检查工具")
    print("=" * 40)
    print("版本: 2.0.0")
    print()
    
    checks = [
        ("Python版本", check_python_version),
        ("依赖包", check_dependencies),
        ("目录结构", check_directories),
        ("API配置", check_api_config),
        ("系统就绪", check_system_ready)
    ]
    
    passed_checks = 0
    total_checks = len(checks)
    
    for check_name, check_func in checks:
        try:
            if check_func():
                passed_checks += 1
        except Exception as e:
            print(f"❌ {check_name}检查出错: {e}")
    
    print(f"\n📊 检查结果: {passed_checks}/{total_checks} 通过")
    
    if passed_checks == total_checks:
        print("\n🎉 系统配置检查全部通过！")
        print("✅ InkAI 已准备就绪，可以开始使用了！")
        print("\n🚀 运行 'python main.py' 开始创作")
    else:
        print("\n⚠️ 系统配置存在问题，请根据上述提示进行修复")
        print("\n🔧 常见解决方案：")
        print("1. 安装依赖: pip install -r requirements.txt")
        print("2. 配置API密钥: 编辑 inkai/utils/config.py")
        print("3. 检查Python版本: python --version")

if __name__ == "__main__":
    main()
