"""
Formalizer/main.py

项目的主入口 (批量处理版 + 进度统计 + 双轨日志)。
- 终端 (Console): 只显示进度和简要结果 (INFO 级别)。
- 日志 (File): 保存所有详细的 Prompt、代码和调试信息 (DEBUG 级别)。
"""

import sys
import os
import json
import argparse
import traceback
import logging
from datetime import datetime

# 确保 'modules' 可以被导入
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from stage1_planner import GoTPlanner
    from stage2_synthesizer import GoTSynthesizer
    from stage3_alignment import SemanticAlignmentModule
    from modules.logger_setup import setup_logging # 确保你创建了这个文件
    import config
except ImportError as e:
    print(f"错误: 无法导入必要的模块。{e}")
    print("请检查是否已创建 'modules/logger_setup.py' 并且其他模块都在正确位置。")
    exit(1)

def save_individual_result(output_dir, index, code, status_report):
    """保存单个问题的 Lean 代码和元数据"""
    # 1. 保存代码
    lean_filename = os.path.join(output_dir, f"problem_{index}.lean")
    try:
        with open(lean_filename, "w", encoding="utf-8") as f:
            f.write(code)
    except IOError: pass

    # 2. 保存报告
    meta_filename = os.path.join(output_dir, f"problem_{index}_report.json")
    try:
        with open(meta_filename, "w", encoding="utf-8") as f:
            json.dump(status_report, f, indent=2, ensure_ascii=False)
    except: pass


def process_single_problem(entry: dict, output_dir: str, image_root_dir: str = None) -> dict:
    """
    处理单个问题。返回结果摘要 dict。
    """
    idx = entry.get("index", "unknown")
    question = entry.get("question", "")
    category = entry.get("category", "Unknown")
    image_file = entry.get("image")

    real_image_path = None
    if image_file and image_root_dir:
        potential_path = os.path.join(image_root_dir, image_file)
        if os.path.exists(potential_path):
            real_image_path = potential_path
            logging.info(f" [Image] 发现关联图片: {real_image_path}")
        else:
            logging.warning(f" [Image] ⚠️ 图片文件未找到: {potential_path}")


    # Stage 1 (分解) & Stage 2 (合成):
    gen_image_path = real_image_path if config.USE_MULTIMODAL else None

    # Stage 3 (语义检测):
    check_image_path = real_image_path

    # [INFO] 打印任务模式信息
    logging.info(f"\n{'=' * 60}")
    logging.info(f" [Task Start] Index: {idx} | Category: {category}")
    logging.info(f" Mode: {'Multimodal' if config.USE_MULTIMODAL else 'Text-Only'}")
    if real_image_path:
        logging.info(f" Logic: 生成{'看' if gen_image_path else '不看'}图, 检测强制看图")
    logging.info(f" Question: {question[:80]}...")
    logging.info(f"{'=' * 60}")

    result_summary = {
        "index": idx,
        "question": question,
        "status": "failed",  # 最终大状态
        "compilation_passed": False,  # 编译是否通过
        "semantic_passed": False,  # 语义是否通过
        "error": None,
        "consistency_level": "N/A",
        "generated_code": ""
    }

    try:
        # --- 阶段一：GoT 分解 ---
        logging.info(f"\n--- [P{idx} 阶段一：分解] ---")
        planner = GoTPlanner()
        graph = planner.run(question, image_path=gen_image_path)

        # --- 阶段二：GoT 合成 ---
        logging.info(f"\n--- [P{idx} 阶段二：合成] ---")
        synthesizer = GoTSynthesizer()
        final_lean_code, synthesized_cache = synthesizer.run(graph, image_path=gen_image_path)
        result_summary["generated_code"] = final_lean_code

        # 检查阶段二是否发生致命错误 (截断逻辑)
        if "-- FATAL:" in final_lean_code:
            logging.warning(f"!! [P{idx}] 阶段二合成失败 (编译未通过)。")
            result_summary["error"] = "Stage 2 Synthesis Failed"
            result_summary["compilation_passed"] = False
            save_individual_result(output_dir, idx, final_lean_code, result_summary)
            return result_summary

        result_summary["compilation_passed"] = True

        # --- 阶段三：语义对齐 (ASCC) ---
        logging.info(f"\n--- [P{idx} 阶段三：对齐] ---")
        aligner = SemanticAlignmentModule()

        is_consistent, report = aligner.run(
            question,
            synthesized_cache,
            graph,
            image_path=check_image_path
        )

        consistency_level = report.get("consistency_level", "level_3")
        result_summary["consistency_level"] = consistency_level
        result_summary["ascc_report"] = report

        if is_consistent:
            result_summary["status"] = "success"
            result_summary["semantic_passed"] = True
            logging.info(f"✅ [P{idx}] 完美通过！(Level: {consistency_level})")
        else:
            result_summary["status"] = "inconsistent"
            result_summary["semantic_passed"] = False
            logging.info(f"⚠️ [P{idx}] 编译通过但语义不一致 (Level: {consistency_level})")

        # 保存此题的文件
        save_individual_result(output_dir, idx, final_lean_code, result_summary)

    except Exception as e:
        err_msg = traceback.format_exc()
        # [ERROR] 简略报错进终端，详细堆栈进日志文件
        logging.error(f"!! [P{idx}] 处理异常: {e}")
        logging.debug(f"详细堆栈:\n{err_msg}")

        result_summary["status"] = "error"
        result_summary["error"] = str(e)

    return result_summary

def main():
    parser = argparse.ArgumentParser(description="批量运行工具")
    parser.add_argument("--input", type=str, default="data.jsonl", help="输入数据文件")
    parser.add_argument("--output_dir", type=str, default=None, help="指定输出目录")
    parser.add_argument("--limit", type=int, default=-1, help="仅运行前 N 个任务")
    parser.add_argument("--multimodal", action="store_true", help="开启多模态 (读取 images/)")
    args = parser.parse_args()

    if args.multimodal:
        config.USE_MULTIMODAL = True
        logging.info("[Config] 多模态已开启 🖼️")

    # 1. 设置输出目录
    if args.output_dir:
        run_output_dir = args.output_dir
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_output_dir = os.path.join(config.BASE_DIR, "batch_results", timestamp)
    os.makedirs(run_output_dir, exist_ok=True)

    # 2. 初始化日志系统 (Log Setup)
    # 详细日志保存到 out.log
    log_file = os.path.join(run_output_dir, "out.log")
    setup_logging(log_file)

    logging.info(f"[BatchRunner] 输出目录: {run_output_dir}")
    logging.info(f"[BatchRunner] 详细日志: {log_file}")

    # 3. 读取数据
    if not os.path.exists(args.input):
        logging.error(f"错误: 找不到输入文件 {args.input}")
        return

    tasks = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                tasks.append(json.loads(line))

    # 处理 limit 参数
    if args.limit > 0:
        tasks = tasks[:args.limit]
        logging.info(f"[BatchRunner] 已限制运行前 {args.limit} 个任务")

    total_tasks = len(tasks)
    logging.info(f"[BatchRunner] 任务总数: {total_tasks}")

    # 4. 统计变量
    compiled_count = 0
    semantic_count = 0

    summary_file = os.path.join(run_output_dir, "summary.jsonl")

    # 5. 主循环
    with open(summary_file, "w", encoding="utf-8") as f_out:
        for i, entry in enumerate(tasks):
            current_idx = i + 1

            input_abs_path = os.path.abspath(args.input)
            input_dir = os.path.dirname(input_abs_path)

            # 这里定义变量名，比如叫 image_search_path
            image_search_path = os.path.join(input_dir, "image")
            # 执行单个任务
            res = process_single_problem(entry, run_output_dir, image_root_dir=image_search_path)

            # 更新统计
            if res["compilation_passed"]:
                compiled_count += 1
            if res["semantic_passed"]:
                semantic_count += 1

            # 实时写入结果摘要
            f_out.write(json.dumps(res, ensure_ascii=False) + "\n")
            f_out.flush()

            # --- 实时进度显示 ---
            comp_rate = (compiled_count / current_idx) * 100
            sem_rate = (semantic_count / current_idx) * 100

            logging.info("\n" + "-"*60)
            logging.info(f"📊 [实时统计] 进度: {current_idx}/{total_tasks}")
            logging.info(f"   🔨 编译通过: {compiled_count}/{current_idx} ({comp_rate:.1f}%)")
            logging.info(f"   ✅ 语义通过: {semantic_count}/{current_idx} ({sem_rate:.1f}%)")
            logging.info("-"*60 + "\n")

    # 6. 最终总结
    logging.info(f"\n{'='*60}")
    logging.info(f" 🎉 批量运行结束")
    logging.info(f" 总任务数: {total_tasks}")
    logging.info(f" 最终编译成功率: {compiled_count}/{total_tasks} ({(compiled_count/total_tasks)*100:.1f}%)")
    logging.info(f" 最终语义通过率: {semantic_count}/{total_tasks} ({(semantic_count/total_tasks)*100:.1f}%)")
    logging.info(f" 结果保存在: {run_output_dir}")
    logging.info(f"{'='*60}")

if __name__ == "__main__":
    main()