"""
Formalizer/stage2_synthesizer.py
"""

import sys
import os
import re
import concurrent.futures
import threading
import logging
import json
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from modules.data_structures import ConceptualGraph, ConceptNode, NodeStatus
    from modules.llm_modules import LLMModules
    from modules.external_tools import LeanCompilerClient
    import config  # 导入配置
    from modules.knowledge_base import load_knowledge_base
except ImportError as e:
    print(f"错误: 无法导入 stage2_synthesizer 所需的模块。{e}")
    exit(1)
except AttributeError as e:
    print(f"错误: config.py 或其他模块可能缺少必要的定义。{e}")
    exit(1)


BASE_IMPORTS = [
    "import Mathlib",

    "import PhysLean.Units.Basic",
    "import PhysLean.Units.Dimension",
    "import PhysLean.Units.WithDim.Basic",  # 处理带单位的量
    "import PhysLean.Units.WithDim.Mass",  # 质量定义
    "import PhysLean.Units.WithDim.Velocity",  # 速度定义
    "import PhysLean.Units.WithDim.Energy",  # 能量定义
    "import PhysLean.SpaceAndTime.Space.Basic",  # 空间定义
    "import PhysLean.SpaceAndTime.Time.Basic",  # 时间定义
    "import PhysLean.SpaceAndTime.Space.Derivatives.Basic",  # 物理中的导数/梯度

    # --- PhysLean: 数学工具 ---
    # 物理常用的特定数学结构
    "import PhysLean.Mathematics.InnerProductSpace.Basic",

    # --- PhysLean: 经典力学 (最常用) ---
    "import PhysLean.ClassicalMechanics.Basic",
    "import PhysLean.ClassicalMechanics.EulerLagrange",  # 拉格朗日力学
    "import PhysLean.ClassicalMechanics.HarmonicOscillator.Basic",
    "import PhysLean.ClassicalMechanics.RigidBody.Basic",

    # --- PhysLean: 电磁学 ---
    "import PhysLean.Electromagnetism.Basic",
    "import PhysLean.Electromagnetism.Electrostatics.Basic",
    "import PhysLean.Electromagnetism.Dynamics.Basic",  # 包含 Hamiltonian/Lagrangian

    # --- PhysLean: 热力学与统计力学 ---
    "import PhysLean.Thermodynamics.Basic",
    "import PhysLean.Thermodynamics.Temperature.Basic",

    # --- PhysLean: 量子力学 ---
    "import PhysLean.QuantumMechanics.FiniteTarget.Basic",
    "import PhysLean.QuantumMechanics.OneDimension.HarmonicOscillator.Basic",

    "import PhysLean.Relativity.LorentzGroup.Basic",
    "import PhysLean.Relativity.Special.ProperTime",

    # --- 常用指令 ---
    "open Real InnerProductSpace",
    "open PhysLean",
    "noncomputable section"
]


class GoTSynthesizer:
    """
    实现阶段二 (GoT 合成) 的主循环。
    """

    def __init__(self):
        try:
            self.llm = LLMModules()
            self.compiler = LeanCompilerClient()
            print("[GoTSynthesizer] 正在加载“已验证知识库”...")
            # [配置] 暂时禁用本地 KB 读取，防止旧依赖干扰
            # self.verified_kb = load_knowledge_base()
            self.verified_kb = {}
            print(f"[GoTSynthesizer] 已加载 {len(self.verified_kb)} 个已验证的节点。")

        except Exception as e:
            print(f"!! [GoTSynthesizer] 初始化失败: {e}")
            raise

        print("[GoTSynthesizer] (阶段二) 已初始化。")


    def _normalize_node_name(self, name: str) -> str:
        import re
        return re.sub(r"\s+", " ", str(name)).strip().lower()

    def _collect_transitive_synthesized_code(self, node, synthesized_cache: dict[str, str], grounded_set: set[str]):
        import re
        code_like = re.compile(r"^\s*(def|theorem|lemma|structure|inductive|namespace)\b", re.M)

        order: list[str] = []
        seen: set[str] = set()
        missing_not_grounded: set[str] = set()

        def dfs(n):
            for d in getattr(n, "dependencies", []):
                dn = self._normalize_node_name(getattr(d, "name", str(d)))
                if dn not in seen:
                    seen.add(dn)
                    dfs(d)
                    if dn in synthesized_cache:
                        order.append(dn)
                    elif dn in grounded_set:
                        pass
                    else:
                        if dn in self.verified_kb:
                            pass
                        else:
                            missing_not_grounded.add(dn)

        dfs(node)

        chunks: list[str] = []
        for dep_name in order:
            dep_code = synthesized_cache.get(dep_name, "")
            if dep_code and code_like.search(dep_code):
                chunks.append(f"-- [Dep] {dep_name}\n{dep_code}")

        return chunks, sorted(missing_not_grounded)

    def _collect_transitive_grounded(self, node, synthesized_cache: dict[str, str], grounded_set: set[str]) -> list[str]:
        """
        收集 node 的传递依赖中属于 grounded 的名称。
        """
        order: list[str] = []
        seen: set[str] = set()

        def dfs(n):
            for d in getattr(n, "dependencies", []):
                dn = self._normalize_node_name(getattr(d, "name", str(d)))
                if dn not in seen:
                    seen.add(dn)
                    dfs(d)
                    if dn in grounded_set and dn not in synthesized_cache:
                        order.append(dn)

        dfs(node)
        dedup, seen2 = [], set()
        for n in order:
            if n not in seen2:
                seen2.add(n)
                dedup.append(n)

        return dedup

    def _recursively_paste_from_kb(self,
                                   node_key: str,
                                   final_code_pieces: list[str],
                                   synthesized_cache: dict[str, str],
                                   grounded_set: set[str]):
        if node_key in synthesized_cache or node_key in grounded_set:
            return

        kb_entry = self.verified_kb.get(node_key)

        if not kb_entry or "code" not in kb_entry or "deps" not in kb_entry:
            print(f"!! [Synthesizer] 警告: 无法在 KB 中找到 '{node_key}' 或条目格式错误。")
            grounded_set.add(node_key)
            return

        for dep_key in kb_entry.get("deps", []):
            self._recursively_paste_from_kb(
                dep_key, final_code_pieces, synthesized_cache, grounded_set
            )

        print(f"[Synthesizer] 从知识库 (KB) 粘贴: {node_key}")
        code_from_kb = kb_entry["code"]

        separator = f"-- {'-' * 30}\n-- Node (from KB): {node_key}\n-- {'-' * 30}"
        formatted_code_block = f"{separator}\n{code_from_kb}"
        final_code_pieces.append(formatted_code_block)

        normalized_name = self._normalize_node_name(node_key)
        synthesized_cache[normalized_name] = code_from_kb


    def _build_final_code_string(self, final_code_pieces: list[str]) -> str:
        import_lines = list(BASE_IMPORTS)
        code_blocks = []

        for piece in final_code_pieces:
            if not piece or not str(piece).strip():
                continue
            lines = str(piece).splitlines()
            others = []
            for ln in lines:
                if re.match(r"^\s*import\s+.+", ln):
                    import_lines.append(re.sub(r"\s+", " ", ln.strip()))
                else:
                    others.append(ln)
            block = "\n".join(others).strip()
            if block:
                code_blocks.append(block)

        seen = set()
        dedup_imports = []
        for line in import_lines:
            if line not in seen:
                seen.add(line)
                dedup_imports.append(line)

        return "\n".join(dedup_imports) + "\n\n" + ("\n\n".join(code_blocks) if code_blocks else "")

    def _synthesis_worker(self, worker_id: int, node_name: str, prompt_context: str,
                          dep_chunks: list, base_imports: list, stop_event: threading.Event,
                          image_path: str = None, original_question: str = "", is_root_node: bool = False):
        """
        Worker: 负责生成、语义预检、编译和反思。
        """
        attempts = getattr(config, 'ATTEMPTS_PER_WORKER', 4)
        current_code = ""
        failed_code = ""
        error_message = ""

        for attempt in range(attempts):
            if stop_event.is_set(): return None

            logging.debug(f"  [Worker-{worker_id}] 尝试 {attempt + 1}/{attempts} ...")

            try:
                # 1. 生成代码
                if attempt == 0:
                    current_code = self.llm.run_synthesis_module(node_name, prompt_context, image_path=image_path)
                else:
                    # 反思修正
                    current_code = self.llm.run_reflection_module(node_name, prompt_context, failed_code, error_message)

                if not current_code or not current_code.strip():
                    failed_code = current_code
                    error_message = "Empty code from LLM."
                    continue

                # =================================================================
                # [新增] 语义拦截 (Semantic Gate) - 仅对 Root Node 生效 (Fail Fast)
                # =================================================================
                # 只有当我们在合成根节点(完整问题)时，才能用全量语义检测来拦截。
                # 如果是 Attempt 0 (初次生成) 且语义严重错误 (Level 3)，直接放弃，不浪费算力编译。
                if attempt == 0 and original_question and is_root_node:
                    logging.debug(f"  [Worker-{worker_id}] (Root Node) 正在进行语义预检...")

                    # 2.1 临时反向翻译
                    back_trans = self.llm.run_back_translation(
                        node_name=node_name,
                        code_chunk=current_code,
                        nl_context="(Context omitted for pre-check)"
                    )

                    # 2.2 语义检查 (ASCC)
                    semantic_report_str = self.llm.run_semantic_check(
                        original_nl=original_question,
                        back_translated_nl=back_trans,
                        image_path=image_path
                    )

                    try:
                        report = json.loads(semantic_report_str)
                        level = report.get("consistency_level", "level_3")

                        if level == "level_3":
                            # [关键逻辑] 语义不通过 -> 直接截断 (Abort)
                            discrepancies = report.get("discrepancies", [])
                            logging.error(f"❌ [Worker-{worker_id}] 根节点语义严重错误 (Level 3)。触发快速失败策略，停止该 Worker。")
                            logging.error(f"   原因: {discrepancies}")
                            return None # 直接返回，不再重试

                    except json.JSONDecodeError:
                        logging.warning(f"  [Worker-{worker_id}] 语义检查 JSON 解析失败，跳过拦截，继续编译。")

                # =================================================================
                # 3. 编译流程 (仅当语义通过 或 非根节点时执行)
                # =================================================================

                import_statements = re.findall(r"^(import .*)$", current_code, re.MULTILINE)
                code_without_imports = re.sub(r"^(import .*)$", "", current_code, flags=re.MULTILINE).strip()

                compile_imports = []
                seen_imp = set()
                for ln in base_imports + [*import_statements]:
                    ln = ln.strip()
                    if ln and ln not in seen_imp:
                        seen_imp.add(ln)
                        compile_imports.append(ln)

                full_code_to_compile = "\n\n".join(filter(None, [
                    "\n".join(compile_imports),
                    "\n\n".join(dep_chunks),
                    code_without_imports
                ]))

                comp_result = self.compiler.compile_code(full_code_to_compile, request_id=f"worker_{worker_id}")

                if comp_result.status == "success":
                    logging.info(f"✅ [Worker-{worker_id}] '{node_name}' 编译成功！")
                    stop_event.set()
                    return code_without_imports
                else:
                    failed_code = current_code
                    error_message = comp_result.error_message or "Unknown error"
                    logging.debug(f"  [Worker-{worker_id}] 编译失败: {error_message[:100]}...")

            except Exception as e:
                logging.debug(f"!! [Worker-{worker_id}] 异常: {e}")
                error_message = str(e)

        return None

    def run(self, graph: ConceptualGraph, image_path: str = None) -> tuple[str, dict[str, str]]:
        logging.info(f"--- [阶段二：GoT 合成 (并发: {config.CONCURRENT_WORKERS})] ---")

        try:
            build_order = graph.get_build_order()
            # 获取根节点名称和原题文本
            root_node_name = graph.root.name
            root_node_norm = self._normalize_node_name(root_node_name)
        except Exception as e:
            logging.error(f"!! [Synthesizer] 错误: 无法获取构建顺序: {e}")
            return "import Mathlib\n\n-- Error: Failed.", {}

        synthesized_cache = {}
        grounded_set = set()
        final_code_pieces = ["\n".join(BASE_IMPORTS)]

        for node in build_order:
            node_name_clean = node.name.strip()
            node_key = node.name.lower().strip()

            # 判断是否为根节点
            is_root = (self._normalize_node_name(node_name_clean) == root_node_norm)

            if node.status == NodeStatus.GROUNDED:
                if node.grounded_definition == "VerifiedKB":
                    self._recursively_paste_from_kb(node_key, final_code_pieces, synthesized_cache, grounded_set)
                else:
                    grounded_set.add(self._normalize_node_name(node_name_clean))
                continue

            elif node.status == NodeStatus.TO_SYNTHESIZE:
                logging.info(f"  [Synthesizer] 正在处理: '{node_name_clean}' (Root: {is_root}) ...")

                dep_chunks, missing = self._collect_transitive_synthesized_code(node, synthesized_cache, grounded_set)
                if missing:
                    logging.warning(f"!! [Synthesizer] 依赖缺失: {missing}")
                    continue

                grounded_names = self._collect_transitive_grounded(node, synthesized_cache, grounded_set)
                prompt_context = "\n\n".join(dep_chunks)

                if grounded_names:
                    prompt_context += "\n\n/-- Grounded references available:\n"
                    for g_name in grounded_names:
                        g_node = graph.find_node_by_name(g_name)
                        if g_node and g_node.grounded_definition:
                            if isinstance(g_node.grounded_definition, list):
                                definitions_str = ", ".join(g_node.grounded_definition)
                                prompt_context += f"- {g_name} corresponds to: {definitions_str}\n"
                            else:
                                prompt_context += f"- {g_name} corresponds to: {g_node.grounded_definition}\n"
                        else:
                            prompt_context += f"- {g_name} (Standard Mathlib concept)\n"

                    prompt_context += "--/"

                stop_event = threading.Event()
                success_code = None

                current_image = image_path

                if current_image:
                    logging.info(f"  [Multimodal] 节点 '{node_name_clean}' 启用图片辅助合成。")

                with concurrent.futures.ThreadPoolExecutor(max_workers=config.CONCURRENT_WORKERS) as executor:
                    futures = []
                    for i in range(config.CONCURRENT_WORKERS):
                        futures.append(executor.submit(
                            self._synthesis_worker,
                            worker_id=i,
                            node_name=node_name_clean,
                            prompt_context=prompt_context,
                            dep_chunks=dep_chunks,
                            base_imports=BASE_IMPORTS,
                            stop_event=stop_event,
                            image_path=current_image,
                            original_question=root_node_name, # 始终传原题
                            is_root_node=is_root # 告诉 worker 只有当这是 True 时才启用拦截
                        ))

                    for future in concurrent.futures.as_completed(futures):
                        result = future.result()
                        if result:
                            success_code = result
                            break

                if success_code:
                    separator = f"-- {'-' * 30}\n-- Node: {node_name_clean}\n-- {'-' * 30}"
                    final_code_pieces.append(f"{separator}\n{success_code}")
                    synthesized_cache[self._normalize_node_name(node_name_clean)] = success_code
                else:
                    logging.error(f"!! [Synthesizer] '{node_name_clean}' 最终合成失败 (可能是语义拦截或编译失败)。")
                    final_code_pieces.append(f"-- FATAL: {node_name_clean} synthesis failed.")
                    return self._build_final_code_string(final_code_pieces), synthesized_cache

        return self._build_final_code_string(final_code_pieces), synthesized_cache