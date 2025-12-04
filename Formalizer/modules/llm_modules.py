"""
Formalizer/modules/llm_modules.py

封装所有 LLM 调用的逻辑。
- 从 config.py 加载配置
- 从 prompts/ 加载模板
- (真实) 调用 LLM API
- 包含清理 LLM 代码输出的逻辑
"""

import time
import ast # 用于安全地解析 LLM 返回的列表字符串
import re  # 用于清理代码块
from dataclasses import dataclass
import os
import traceback
import logging
import base64
import mimetypes

# 导入配置
try:
    import config
except ImportError:
    print("错误：config.py 未找到。请确保它在 Formalizer/ 目录中。")
    exit(1)

try:
    from openai import OpenAI, APIConnectionError, RateLimitError, APIError, APIStatusError
    # 检查 API 密钥是否存在且非默认值
    if not config.LLM_API_KEY or config.LLM_API_KEY == "YOUR_API_KEY_HERE":
         print("!! 警告: LLM_API_KEY 未在 config.py 中正确设置。")

    print(f"[LLMModules] 正在初始化 真实 OpenAI 客户端...")
    print(f"[LLMModules] Base URL: {config.LLM_BASE_URL}")
    client = OpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL
    )
except ImportError:
    print("错误: 'openai' 库未安装。") #
    print("请运行 'pip install openai' 来安装它。")
    exit(1)
except Exception as e:
    print(f"!! [LLMModules] 初始化 OpenAI 客户端时出错: {e}")
    exit(1)


@dataclass
class GroundingResult:
    """封装接地推理器的输出""" #
    is_found: bool
    definitions: list[str] = None

def _clean_llm_code_output(response: str) -> str:
    """
    使用正则表达式查找并提取 Lean 代码块 (```lean ... ``` 或 ``` ... ```)，
    并移除首尾空格。
    如果找不到代码块，则假定整个响应是代码并进行清理。
    也处理 Expander 可能返回的 ```python ... ``` 块。
    """
    cleaned = response.strip()
    original_cleaned = cleaned

    match_lean = re.search(r"```lean\s*([\s\S]*?)\s*```", cleaned, re.DOTALL)
    if match_lean:
        return match_lean.group(1).strip()

    match_python = re.search(r"```python\s*([\s\S]*?)\s*```", cleaned, re.DOTALL)
    if match_python:
        return match_python.group(1).strip()

    match_plain = re.search(r"```\s*([\s\S]*?)\s*```", cleaned, re.DOTALL)
    if match_plain:
        cleaned = match_plain.group(1).strip()
        if cleaned.startswith("python\n") or cleaned.startswith("python\r\n"):
            cleaned = cleaned.split('\n', 1)[1].strip()
        return cleaned

    if cleaned.startswith('`') and cleaned.endswith('`'):
         cleaned = cleaned[1:-1]

    stop_markers = [
        "-- [Dep]",  # 标准标记
        "--[Dep]",  # 变体：无空格
        "import Mathlib"
    ]

    lines = cleaned.split('\n')
    valid_lines = []

    for i, line in enumerate(lines):
        line_stripped = line.strip()

        should_cut = False

        if line_stripped.startswith("import Mathlib") and i > 5:
            should_cut = True

        for marker in stop_markers:
            if marker != "import Mathlib" and marker in line:
                should_cut = True
                break

        if should_cut:
            logging.debug(f"  [Cleaner] 触发截断逻辑，拦截词: '{line_stripped[:20]}...'")
            break

        valid_lines.append(line)

    cleaned = "\n".join(valid_lines).strip()

    if "-- >> (Optional) Auxiliary Types" in cleaned:
        cleaned = cleaned.split("-- >> (Optional) Auxiliary Types")[0].strip()

    return cleaned


def _encode_image(image_path: str) -> str:
    """读取图片并转换为 base64 编码字符串"""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        logging.error(f"!! 无法读取图片 {image_path}: {e}")
        return None

class LLMModules:
    """
    封装所有 LLM 调用
    """
    def __init__(self):
        print(f"[LLMModules] 初始化...")
        print(f"[LLMModules] 模型: {config.LLM_MODEL_NAME}")

        # 1. 在初始化时加载所有 Prompt 模板
        try:
            with open(config.GROUNDING_PROMPT_FILE, 'r', encoding='utf-8') as f:
                self.grounding_prompt_template = f.read()
            with open(config.EXPANSION_PROMPT_FILE, 'r', encoding='utf-8') as f:
                self.expansion_prompt_template = f.read()
            # 加载 Stage 2 prompts
            with open(config.SYNTHESIS_PROMPT_FILE, 'r', encoding='utf-8') as f:
                self.synthesis_prompt_template = f.read()
            with open(config.REFLECTION_PROMPT_FILE, 'r', encoding='utf-8') as f:
                self.reflection_prompt_template = f.read()
            with open(config.BACK_TRANSLATION_PROMPT_FILE, 'r', encoding='utf-8') as f:
                self.back_translation_prompt_template = f.read()
            with open(config.MERGE_BACK_TRANSLATIONS_PROMPT_FILE, 'r', encoding='utf-8') as f:
                self.merge_back_translations_prompt_template = f.read()
            with open(config.SEMANTIC_CHECK_PROMPT_FILE, 'r', encoding='utf-8') as f:
                self.semantic_check_prompt_template = f.read()

            print("[LLMModules] 所有 Prompt 模板加载成功。")
        except FileNotFoundError as e:
            print(f"错误: Prompt 文件未找到。{e}") #
            print(f"请确保 prompts/ 目录和 .txt 文件存在于 {config.FORMALIZER_DIR} 中。")
            exit(1)
        except AttributeError as e:
             print(f"错误: config.py 可能缺少 Prompt 文件路径定义。{e}")
             exit(1)

    def _call_llm_api(self, prompt: str, temperature: float = None, image_path: str = None) -> str:
        """
        封装 API 调用，支持多模态。
        """
        if temperature is None:
            temperature = getattr(config, 'LLM_TEMPERATURE_STRICT', 0.1)

        use_image = (image_path is not None)

        logging.debug(f"--- [LLM API 调用 (Temp: {temperature}, Image: {use_image})] ---")
        # logging.debug(f"Prompt:\n{prompt[:500]}...") # 可以保留

        user_content = []

        user_content.append({"type": "text", "text": prompt})

        if use_image:
            base64_image = _encode_image(image_path)
            if base64_image:
                mime_type, _ = mimetypes.guess_type(image_path)
                if not mime_type: mime_type = "image/png"  # 默认

                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64_image}"
                    }
                })
                logging.debug(f"  [Multimodal] 已附加图片: {image_path}")

        try:
            final_content = user_content if use_image else prompt

            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are an AI assistant expert in Lean 4 and Mathlib."},
                    {"role": "user", "content": final_content}
                ],
                model=config.LLM_MODEL_NAME,
                temperature=temperature,
            )
            response = chat_completion.choices[0].message.content
            response_text = response if response else ""

            logging.debug(f"响应 (REAL):\n{response_text}")
            logging.debug(f"--- [LLM API 结束] ---")
            return response_text.strip()

        except APIConnectionError as e:
            logging.error(f"!! LLM API 调用失败: 无法连接到服务器 {e}")

        except RateLimitError as e:
            logging.error(f"!! LLM API 调用失败: 达到速率限制 {e}")

        except APIStatusError as e:
            logging.error(f"!! LLM API 调用失败: API 返回状态错误 {e.status_code}")
            logging.error(f"   响应: {e.response}")

        except APIError as e:
            logging.error(f"!! LLM API 调用失败: OpenAI API 错误 {e}")

        except KeyError as e:
            logging.error(f"!! LLM API 调用期间捕获到 KeyError: {repr(e)}")
            logging.error(f"   (发生在处理 Prompt 的 API 调用中)")

        except Exception as e:
            logging.error(f"!! LLM API 调用失败: 发生未知错误")
            logging.error(f"   异常类型: {type(e)}")
            logging.error(f"   异常信息: {repr(e)}")
            logging.debug(traceback.format_exc()) # 堆栈信息只进 debug 日志

        return ""

    def run_grounding_reasoner(self, concept_name: str, candidates: list, image_path: str = None) -> GroundingResult:
        """
        LLM 扮演“接地推理器”角色。
        """
        # (candidates 来自 external_tools)
        candidates_text = "\n".join([f"- {c.full_lean_name}: {c.informal_description or '(No description)'}" for c in candidates]) #
        if not candidates_text:
            candidates_text = "(无候选结果)" #

        prompt = self.grounding_prompt_template.format( #
            concept_name=concept_name,
            candidates_text=candidates_text
        )

        response = self._call_llm_api(prompt, image_path=image_path)

        # 解析响应
        if response.startswith("FOUND:"):
            #return GroundingResult(is_found=True, definition=response.split(":", 1)[1].strip())
            content = response.split(":", 1)[1].strip()
            defs = []
            try:
                # 尝试解析 Python 列表格式 ['A', 'B']
                parsed = ast.literal_eval(content)
                if isinstance(parsed, list):
                    defs = [str(x).strip() for x in parsed]
                else:
                    defs = [str(parsed).strip()]
            except:
                # 如果解析失败，回退到逗号分隔: Def A, Def B
                defs = [x.strip() for x in content.split(',') if x.strip()]

            # 限制最多 3 个
            return GroundingResult(is_found=True, definitions=defs[:3])
        else:
            if not response.startswith("NO_MATCH"):
                logging.warning(f"  [LLM Reasoner] 警告: 异常响应: '{response}'")
            #return GroundingResult(is_found=False)
            return GroundingResult(is_found=False, definitions=[])

    def run_expansion_module(self, concept_name: str, image_path: str = None) -> list[str]:
        """
        LLM 扮演“分解器”角色。
        """
        prompt = self.expansion_prompt_template.format(concept_name=concept_name)

        response = self._call_llm_api(prompt, image_path=image_path)

        cleaned_response = _clean_llm_code_output(response)
        try:
            result_list = ast.literal_eval(cleaned_response)
            if isinstance(result_list, list):
                return [str(item).strip() for item in result_list if str(item).strip()]
        except (ValueError, SyntaxError) as e:
            logging.warning(f"!! LLM Expander 警告: 无法解析响应。错误: {e}")
            pass
        return []

    def run_synthesis_module(self, target_name: str, dependency_context: str, image_path: str = None) -> str:
        prompt = self.synthesis_prompt_template.format(
            dependency_context=dependency_context,
            target_name=target_name
        )
        logging.debug(f"  [Synthesizer] 生成 '{target_name}'...")

        creative_temp = getattr(config, 'LLM_TEMPERATURE_CREATIVE', 0.1)

        response = self._call_llm_api(prompt, temperature=creative_temp, image_path=image_path)

        return _clean_llm_code_output(response)

    def run_reflection_module(self, target_name: str, dependency_context: str, failed_code: str,
                              error_message: str) -> str:
        """
        LLM 扮演“代码修正器”角色。
        """
        cleaned_error = error_message.split("error:", 1)[-1].strip()
        max_error_len = 500
        if len(cleaned_error) > max_error_len:
            cleaned_error = cleaned_error[:max_error_len] + "\n... (错误信息过长已截断)"

        prompt = self.reflection_prompt_template.format(
            dependency_context=dependency_context,
            target_name=target_name,
            failed_code=failed_code,
            error_message=cleaned_error
        )

        logging.debug(f"  [LLM Reflector] 正在运行 Prompt (修正 '{target_name}')...")

        response = self._call_llm_api(prompt)
        cleaned_response = _clean_llm_code_output(response)

        return cleaned_response

    def run_back_translation(self, node_name: str, code_chunk: str, nl_context: str) -> str:
        if not nl_context:
            nl_context = "(无依赖项)"

        prompt = self.back_translation_prompt_template.format(
            node_name=node_name,
            code_chunk=code_chunk,
            nl_context=nl_context
        )
        response = self._call_llm_api(prompt)
        return response.strip()

    def run_merge_back_translations(self, segments: dict[str, str]) -> str:
        segments_text = "\n".join(
            f"--- 片段: {name} ---\n{description}\n"
            for name, description in segments.items()
        )

        prompt = self.merge_back_translations_prompt_template.format(
            segments_text=segments_text
        )
        response = self._call_llm_api(prompt)
        return response.strip()

    def run_semantic_check(self, original_nl: str, back_translated_nl: str, image_path: str = None) -> str:

        prompt = self.semantic_check_prompt_template.format(
            original_problem=original_nl,
            back_translated_problem=back_translated_nl
        )

        response = self._call_llm_api(prompt, image_path=image_path)

        cleaned_response = _clean_llm_code_output(response)

        if not cleaned_response.startswith("{") or not cleaned_response.endswith("}"):
            logging.warning(f"!! [LLM ASCC] 警告: 响应不是 JSON。")
            logging.debug(f"   原始响应: {cleaned_response}")
            return """
            {
                "consistency_level": "level_3",
                "discrepancies": ["ASCC 模块返回了无效的 JSON 对象。"],
                "recommendations": []
            }
            """

        return cleaned_response