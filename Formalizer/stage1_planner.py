"""
stage1_planner.py

实现了“阶段一：GoT 分解” (GoT Decomposition)。
- 包含“简单规划器”逻辑
- 在 `run` 方法中添加了对 KB 的 `if key in kb:` 检查。
"""

from collections import deque
from modules.data_structures import ConceptualGraph, NodeStatus, ConceptNode
from modules.llm_modules import LLMModules
from modules.external_tools import LeanSearchClient
from modules.knowledge_base import load_knowledge_base


class GoTPlanner:
    """
    实现阶段一 (GoT 分解) 的主循环。
    """

    def __init__(self):
        # 注入所有需要的模块
        self.llm = LLMModules()
        self.lean_search = LeanSearchClient()  # 初始化外部工具

        print("[GoTPlanner] 正在加载“已验证知识库”...")
        # 加载 KB (格式: {"key": {"code": "...", "deps": [...]}})
        #self.verified_kb = load_knowledge_base()
        self.verified_kb = {}
        print(f"[GoTPlanner] 已加载 {len(self.verified_kb)} 个已验证的节点。")

        print("GoTPlanner (阶段一) 已初始化。")

    def run(self, informal_statement: str, image_path: str = None) -> ConceptualGraph:
        """
        主方法：执行完整的阶段一分解流程。
        (混合逻辑: 强制分解根节点, 然后广度优先处理子节点并修复共享依赖)
        V2 Update: 引入双轨 Grounding (文本+视觉) 策略。
        """
        print(f"\n--- [阶段一：GoT 分解] 开始 (输入: '{informal_statement}') ---")
        graph = ConceptualGraph(root_name=informal_statement)

        # queue 只存储待处理的 *子* 节点
        queue = deque()

        # queue_log 跟踪哪些节点 *已经或即将在* 队列中处理
        # (我们先把 root 加进去，因为它被特殊处理了)
        queue_log = {graph.root.name.lower().strip()}

        # --- 步骤 1: 特殊处理根节点 (来自用户的原始逻辑) ---
        print(f"\n[Planner] 步骤 1: 优先分解根节点 '{graph.root.name}'...")
        graph.root.status = NodeStatus.TO_SYNTHESIZE
        print(f"[Planner] 状态更新: {graph.root.name} -> 🛠️ TO_SYNTHESIZE (强制分解)")

        # 运行分解
        dependency_names = self.llm.run_expansion_module(graph.root.name, image_path=image_path)

        print(f"\n[Planner] 步骤 2: 将根节点的依赖项加入队列...")
        for name in dependency_names:
            name_key = name.lower().strip()
            if not name_key: continue

            # 检查节点是否已在图中 (虽然在这一步它们不应该存在)
            existing_node = graph.find_node_by_name(name_key)

            if existing_node:
                if existing_node not in graph.root.dependencies:
                    graph.root.dependencies.append(existing_node)
                    print(f"[Planner] 链接到 *已有* 依赖: {name}")
            else:
                new_node = graph.add_node(name=name, parent=graph.root)

                if name_key not in queue_log:
                    queue.append(new_node)
                    queue_log.add(name_key)  # 标记为“已入队”
                    print(f"[Planner] 新依赖项加入队列: {name}")

        # --- 步骤 3: 开始 '广度优先' 处理 *子节点* 队列 ---
        print("\n[Planner] 步骤 3: 开始 '广度优先' 分解与接地 *子节点*...")

        while queue:
            current_node = queue.popleft()
            current_name_key = current_node.name.lower().strip()
            print(f"\n[Planner] 正在处理: '{current_node.name}'")

            # 3a. 检查本地知识库 (KB)
            if current_name_key in self.verified_kb:
                current_node.status = NodeStatus.GROUNDED
                # [修正] 保持数据结构一致性，改为列表格式
                current_node.grounded_definition = ["VerifiedKB"]

                print(f"[Planner] 状态更新: {current_node.name} -> ✅ GROUNDED (来自本地知识库!)")
                continue

            # 3b. 接地模块 (RAG) - (如果 KB 中未找到)
            search_results = self.lean_search.search(current_node.name)

            # =======================================================
            # [核心修改] 双轨 Grounding：文本通道 + 视觉通道 -> 合并
            # =======================================================
            print(f"  [Planner] 正在执行双轨接地 (Text + Vision)...")

            # 通道一：纯文本 Grounding (强制 image_path=None)
            res_text = self.llm.run_grounding_reasoner(
                concept_name=current_node.name,
                candidates=search_results,
                image_path=None
            )

            # 通道二：视觉增强 Grounding (仅当有多模态输入时)
            res_vision = None
            if image_path:
                res_vision = self.llm.run_grounding_reasoner(
                    concept_name=current_node.name,
                    candidates=search_results,
                    image_path=image_path
                )

            # 结果合并 (使用 Set 自动去重)
            combined_defs = set()

            # 收集文本通道结果
            if res_text.is_found and res_text.definitions:
                combined_defs.update(res_text.definitions)

            # 收集视觉通道结果
            if res_vision and res_vision.is_found and res_vision.definitions:
                combined_defs.update(res_vision.definitions)

            final_definitions = list(combined_defs)

            if final_definitions:
                current_node.status = NodeStatus.GROUNDED
                current_node.grounded_definition = final_definitions  # 这是一个列表

                print(f"[Planner] 状态更新: {current_node.name} -> ✅ GROUNDED (Matches: {final_definitions})")
                print(f"  > 文本通道: {res_text.definitions if res_text.is_found else []}")
                if image_path:
                    print(f"  > 视觉通道: {res_vision.definitions if (res_vision and res_vision.is_found) else []}")
                continue

            # 3c. 扩展模块 (LLM 分解) - (如果 KB 和 Mathlib 都未找到)
            current_node.status = NodeStatus.TO_SYNTHESIZE
            print(f"[Planner] 状态更新: {current_node.name} -> 🛠️ TO_SYNTHESIZE (将进行分解...)")

            dependency_names_loop = self.llm.run_expansion_module(current_node.name, image_path=image_path)

            for name in dependency_names_loop:
                name_key = name.lower().strip()
                if not name_key: continue

                existing_node = graph.find_node_by_name(name_key)

                if existing_node:
                    # [保留] 自循环检查
                    if existing_node.id == current_node.id:
                        print(f"[Planner] 警告: LLM (Expander) 尝试为 '{name}' 创建一个自循环，已忽略。")
                        continue

                    if existing_node not in current_node.dependencies:
                        current_node.dependencies.append(existing_node)
                        print(f"[Planner] 链接到 *已有* 依赖: {name}")
                else:
                    new_node = graph.add_node(name=name, parent=current_node)

                    if name_key not in queue_log:
                        queue.append(new_node)
                        queue_log.add(name_key)
                        print(f"[Planner] 新依赖项加入队列: {name}")

        print(f"\n--- [阶段一：GoT 分解] 完成 (输入: '{informal_statement}') ---")
        return graph


def print_graph_tree(node, indent=""):
    """辅助函数：漂亮地打印依赖图"""
    status_emoji = {
        NodeStatus.GROUNDED: "✅",
        NodeStatus.TO_SYNTHESIZE: "🛠️",
        NodeStatus.TO_EXPAND: "❓"
    }
    def_name = ""
    if node.grounded_definition == "VerifiedKB":
        def_name = " (as: VerifiedKB)"
    elif node.grounded_definition:
        def_name = f" (as: {node.grounded_definition})"

    print(f"{indent}{status_emoji.get(node.status, '❓')} {node.name}{def_name}")
    for dep in node.dependencies:
        print_graph_tree(dep, indent + "  ")


def demonstrate_stage1_to_stage2_interface(graph: ConceptualGraph):
    """
    演示为阶段二准备的接口 (.get_build_order())
    """
    print("\n--- [为阶段二准备的接口演示] ---")
    print("阶段二 (合成) 将按以下“自下而上”的顺序执行：")

    build_order = graph.get_build_order()

    for i, node in enumerate(build_order):
        print(f"  步骤 {i + 1}: ", end="")
        if node.status == NodeStatus.GROUNDED:
            if node.grounded_definition == "VerifiedKB":
                print(f"使用本地知识库 (KB) 定义 '{node.name}'")
            else:
                print(f"使用 Mathlib 定义 '{node.grounded_definition or node.name}'")
        elif node.status == NodeStatus.TO_SYNTHESIZE:
            print(f"**生成** '{node.name}' (依赖: {[dep.name for dep in node.dependencies]})")


if __name__ == "__main__":
    # 我们可以在这里运行测试
    print("=" * 40)
    print(" 运行示例 1：Koethe 猜想 ")
    print("=" * 40)

    planner = GoTPlanner()
    graph1 = planner.run("""Prove that if $H$ is a subgroup of $G$ of index $n$, then there is a normal subgroup $K$ of $G$ such that $K\leq H$ and $[G:K]\leq n!$""")

    print("\n[阶段一 最终输出：依赖图]")
    print_graph_tree(graph1.root)

    demonstrate_stage1_to_stage2_interface(graph1)