"""
Formalizer/test_expansion.py

一个简单、专注的测试脚本。
目标：只测试 LLM 的“概念分解”功能是否正常。
它会：
1. 加载 LLM 模块 (这会初始化 API 客户端)。
2. 调用 run_expansion_module()。
3. 打印 LLM 的真实输出。
"""

import sys
import os

# 确保 'modules' 可以被导入
# (这会将 'Formalizer/' 目录添加到 Python 路径中)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from modules.llm_modules import LLMModules
    import config  # 确保 config 被加载并验证
except ImportError as e:
    print(f"错误: 无法导入模块。{e}")
    print("请确保你在项目根目录，并使用 'python3 Formalizer/test_expansion.py' 运行")
    exit(1)

if __name__ == "__main__":

    print("=" * 40)
    print("--- 启动 LLM 分解模块 (Expansion) 单元测试 ---")
    print("=" * 40)

    # 1. 初始化模块
    # (这会加载 prompt 和真实的 API 客户端)
    try:
        llm = LLMModules()
    except Exception as e:
        print(f"!! LLM 模块初始化失败: {e}")
        exit(1)

    # 2. 定义我们要测试的“题目”
    concept_to_test = " 正六棱柱"

    print(f"\n[测试] 正在调用 LLM 分解: '{concept_to_test}'")

    # 3. 运行分解逻辑
    # 这将：
    # a. 加载 prompts/expansion_module.txt
    # b. 格式化 Prompt
    # c. 调用真实的 LLM API
    # d. 解析 LLM 返回的列表
    try:
        dependencies = llm.run_expansion_module(concept_to_test)

        print("\n--- [测试结果] ---")
        print(f"原始概念: '{concept_to_test}'")
        print(f"LLM 返回的依赖: {dependencies}")

        if isinstance(dependencies, list) and len(dependencies) > 0:
            print("\n[测试通过] ✅ LLM API 调用成功并返回了一个列表。")
        elif isinstance(dependencies, list) and len(dependencies) == 0:
            print("\n[测试通过] ✅ LLM API 调用成功，但返回了一个空列表。")
            print("   (这可能是 LLM 无法分解此概念，但 API 本身是通的)")
        else:
            print("\n[测试失败] ❌ LLM 返回的不是一个列表。")

    except Exception as e:
        print(f"\n!! [测试失败] ❌ 在 API 调用期间发生意外错误: {e}")

    print("\n--- LLM 分解测试完成 ---")