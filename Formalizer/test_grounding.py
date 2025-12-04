"""
Formalizer/test_grounding.py

专门用于测试 Stage 1 的“接地”流程：
1. 调用 LeanSearchClient.search() 获取指定概念的候选结果。
2. 将结果喂给 LLMModules.run_grounding_reasoner()。
3. 清晰地打印出搜索结果和最终的接地决策。
"""

import sys
import os
import argparse  # 用于接收命令行参数

# 确保 'modules' 可以被导入
# (这会将 'Formalizer/' 目录添加到 Python 路径中)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from modules.external_tools import LeanSearchClient, LeanSearchResult
    from modules.llm_modules import LLMModules, GroundingResult
    import config  # 确保 config 被加载并验证
except ImportError as e:
    print(f"错误: 无法导入模块。{e}")
    print("请确保你在项目根目录，并使用 'python3 Formalizer/test_grounding.py <概念名>' 运行")
    exit(1)
except AttributeError as e:
    print(f"错误: config.py 或其他模块可能缺少必要的定义。{e}")
    exit(1)


def main(concept_name: str):
    """执行接地测试的函数"""
    print("=" * 50)
    print(f"--- 启动接地测试 (概念: '{concept_name}') ---")
    print("=" * 50)

    # 1. 初始化模块
    try:
        print("\n[初始化] 正在初始化 LeanSearchClient...")
        lean_search = LeanSearchClient()
        print("[初始化] 正在初始化 LLMModules...")
        llm = LLMModules()
        print("[初始化] 初始化完成。")
    except Exception as e:
        print(f"!! [初始化失败]: {e}")
        return

    # 2. 调用 LeanSearch
    print(f"\n[步骤 1] 调用 LeanSearch API 搜索 '{concept_name}'...")
    try:
        search_results: list[LeanSearchResult] = lean_search.search(concept_name)
    except Exception as e:
        print(f"!! [LeanSearch 失败]: 调用 search() 时发生错误: {e}")
        return

    # 3. 打印 LeanSearch 返回的详细结果
    print("\n" + "-" * 50)
    print(f"[步骤 2] LeanSearch 返回了 {len(search_results)} 个结果:")
    print("-" * 50)
    if not search_results:
        print("(无结果)")
    else:
        for i, result in enumerate(search_results):
            print(f"  结果 {i + 1}:")
            print(f"    Lean Name: {result.full_lean_name}")
            # 使用 getattr 安全地访问属性，以防 LeanSearchResult 结构变化
            desc = getattr(result, 'informal_description', '(属性不存在)')
            print(f"    描述: {desc or '(无描述)'}")
            # 你可以在这里打印更多字段，如果 LeanSearchResult 有的话
            # print(f"    Distance: {getattr(result, 'distance', 'N/A')}")
    print("-" * 50)

    # 4. 调用 LLM 接地推理器
    print(f"\n[步骤 3] 将搜索结果传递给 LLM 接地推理器...")
    try:
        grounding_decision: GroundingResult = llm.run_grounding_reasoner(concept_name, search_results)
    except Exception as e:
        print(f"!! [LLM Reasoner 失败]: 调用 run_grounding_reasoner() 时发生错误: {e}")
        return

    # 5. 打印最终决策
    print("\n" + "=" * 50)
    print(f"[步骤 4] LLM 接地推理器的最终决策:")
    print("=" * 50)
    if grounding_decision.is_found:
        print(f"✅ FOUND: '{grounding_decision.definition}'")
    else:
        print(f"❌ NO_MATCH")
    print("=" * 50)

    print("\n--- 接地测试完成 ---")


if __name__ == "__main__":
    # 设置命令行参数解析器
    parser = argparse.ArgumentParser(description="测试 Stage 1 的接地流程。")
    parser.add_argument("concept_name", type=str, help="要测试接地的概念名称 (例如: angle, ring, IsNilpotent)")

    args = parser.parse_args()

    # 运行主测试函数
    main(args.concept_name)