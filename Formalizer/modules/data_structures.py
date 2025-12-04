"""
modules/data_structures.py

定义项目的核心数据结构：
- NodeStatus (Enum)
- ConceptNode (Class)
- ConceptualGraph (Class)
"""

import uuid
from enum import Enum, auto
from collections import deque


class NodeStatus(Enum):
    """
    定义一个概念节点在分解阶段的几种可能状态
    """
    TO_EXPAND = auto()  # 待处理
    GROUNDED = auto()  # ✅ 已接地：在 Mathlib 中找到
    TO_SYNTHESIZE = auto()  # 🛠️ 待合成：Mathlib 中未找到


class ConceptNode:
    """
    概念依赖图中的一个节点。
    """

    def __init__(self, name: str, parent=None):
        self.id = str(uuid.uuid4())
        self.name: str = name.strip()
        self.status: NodeStatus = NodeStatus.TO_EXPAND
        self.dependencies: list['ConceptNode'] = []
        self.parent: 'ConceptNode' | None = parent

        # 如果 status == GROUNDED，这里将存储 Mathlib 中的权威定义名称
        #self.grounded_definition: str | None = None
        self.grounded_definition: list[str] = []
        self.grounding_info: dict | None = None
        # (可选) 存储接地失败时的参考片段信息
        # self.reference_snippet: str | None = None
        # self.reference_info: dict | None = None # 或者存储更完整的 LeanSearchResult

    def __repr__(self):
        return f"Node(name='{self.name.strip()}', status={self.status.name})"


class ConceptualGraph:
    """
    “代理的工作记忆”，存储整个依赖图。
    这是 Stage 1 的最终输出，也是 Stage 2 的主要输入。
    """

    def __init__(self, root_name: str):
        self.root = ConceptNode(name=root_name)
        self.nodes: dict[str, ConceptNode] = {self.root.id: self.root}

        # 按名称索引所有节点，用于快速查找共享依赖
        self._nodes_by_name: dict[str, ConceptNode] = {
            self.root.name.lower().strip(): self.root
        }

    def add_node(self, name: str, parent: ConceptNode) -> ConceptNode:
        """在图中添加一个新节点作为某个节点的依赖项"""
        # ConceptNode 的 __init__ 会自动 strip() name
        new_node = ConceptNode(name=name, parent=parent)
        parent.dependencies.append(new_node)
        self.nodes[new_node.id] = new_node

        # 将新节点添加到名称索引中
        self._nodes_by_name[new_node.name.lower().strip()] = new_node

        return new_node

    def find_node_by_name(self, name: str) -> ConceptNode | None:
        """
        通过规范化（小写、去空格）的名称在图中查找一个 *已存在* 的节点。
        """
        return self._nodes_by_name.get(name.lower().strip())

    def get_build_order(self) -> list[ConceptNode]:
        """
        **为阶段二提供的核心接口**

        执行拓扑排序（后序遍历），返回一个“自下而上”的节点构建列表。
        阶段二（合成）将严格按照这个列表的顺序来生成代码。
        """
        build_order = []
        visited = set()

        def post_order_traverse(node: ConceptNode):
            if node.id in visited:
                return
            visited.add(node.id)

            # 先递归访问所有依赖项
            for dep in node.dependencies:
                post_order_traverse(dep)

            # 在所有依赖项都处理完毕后，再将当前节点加入列表
            build_order.append(node)

        post_order_traverse(self.root)
        return build_order