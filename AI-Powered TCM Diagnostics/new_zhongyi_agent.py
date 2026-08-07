# -*- coding: utf-8 -*-
"""
中医知识问答系统 - 基于 RAG（检索增强生成）的中医证候问答系统

功能：
1. 基于向量索引的问答（LlamaIndex + DashScope）
2. RAGAS 评估框架自动评测（--eval 时按需加载）
3. Gradio Web 界面（--webui 或默认）

用法：
    python new_zhongyi_agent.py              # 启动 Web UI
    python new_zhongyi_agent.py --webui      # 启动 Web UI
    python new_zhongyi_agent.py --eval       # 完整 RAGAS 评估（生成 QA + 评估）
    python new_zhongyi_agent.py --eval-only  # 仅用已有 CSV 跑 RAGAS（跳过 QA 生成）
    python new_zhongyi_agent.py --debug      # 开启 LlamaIndex 调试日志
"""

import argparse
import json
import logging
import os
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List, Mapping, Optional, Tuple, Union

import gradio as gr
import pandas as pd
from llama_index.core import (
    PromptTemplate,
    Settings,
    SimpleDirectoryReader,
    StorageContext,
    load_index_from_storage,
)
from llama_index.core.callbacks import CallbackManager, LlamaDebugHandler
from llama_index.embeddings.dashscope import (
    DashScopeEmbedding,
    DashScopeTextEmbeddingModels,
)
from llama_index.llms.dashscope import DashScope, DashScopeGenerationModels

from backend.rag import execute_rag_query, format_answer_with_citations
from backend.security import DISCLAIMER

# ============================================================
# 路径与日志
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
DOC_EMB_DIR = BASE_DIR / "doc_emb"
DATA_DIR = BASE_DIR / "data"

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ============================================================
# 全局单例
# ============================================================
_query_engine = None
_index = None
_models_configured = False

# RAGAS 相关对象（仅 --eval 时初始化）
_langchain_llm = None
_langchain_embeddings = None


def require_api_key() -> str:
    """校验 DashScope API Key 是否已配置。"""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "未设置环境变量 DASHSCOPE_API_KEY，请先执行：export DASHSCOPE_API_KEY='你的密钥'"
        )
    return api_key


def configure_models(debug: bool = False) -> None:
    """初始化全局 LLM / Embedding，仅执行一次。"""
    global _models_configured
    if _models_configured:
        return

    api_key = require_api_key()
    Settings.llm = DashScope(
        model_name=DashScopeGenerationModels.QWEN_MAX,
        api_key=api_key,
    )
    Settings.embed_model = DashScopeEmbedding(
        model_name=DashScopeTextEmbeddingModels.TEXT_EMBEDDING_V1,
        api_key=api_key,
    )

    if debug or os.getenv("ZHONGYI_DEBUG", "").lower() in ("1", "true", "yes"):
        llama_debug = LlamaDebugHandler(print_trace_on_end=True)
        Settings.callback_manager = CallbackManager([llama_debug])
        logger.info("LlamaIndex 调试模式已开启")
    else:
        Settings.callback_manager = None

    _models_configured = True


def load_query_engine():
    """加载持久化向量索引并构建查询引擎。"""
    global _index

    if not DOC_EMB_DIR.is_dir():
        raise FileNotFoundError(f"索引目录不存在: {DOC_EMB_DIR}")

    qa_prompt_tmpl = PromptTemplate(
        "你是一位资深的中医专家，擅长辨证论治。\n"
        "上下文信息如下：\n"
        "------------------\n"
        "{context_str}\n"
        "------------------\n"
        "请严格根据上述上下文信息回答以下问题。如果上下文中没有相关信息，请明确说明。\n"
        "问题：{query_str}\n"
        "回答："
    )
    refine_prompt_tmpl = PromptTemplate(
        "原始问题：{query_str}\n"
        "现有答案：{existing_answer}\n"
        "补充上下文：\n"
        "----------------\n"
        "{context_msg}\n"
        "----------------\n"
        "请根据补充的上下文优化上述答案。如果补充上下文无帮助，返回原答案。\n"
        "优化后的答案："
    )

    storage_context = StorageContext.from_defaults(persist_dir=str(DOC_EMB_DIR))
    index = load_index_from_storage(storage_context)
    _index = index

    query_engine = index.as_query_engine(similarity_top_k=5, streaming=False)
    query_engine.update_prompts(
        {
            "response_synthesizer:text_qa_template": qa_prompt_tmpl,
            "response_synthesizer:refine_template": refine_prompt_tmpl,
        }
    )

    logger.info("查询引擎加载完成，自定义提示模板已应用")
    return query_engine


def get_query_engine():
    """获取全局查询引擎单例。"""
    global _query_engine
    configure_models()
    if _query_engine is None:
        _query_engine = load_query_engine()
    return _query_engine


def get_index_nodes() -> list:
    """从已加载索引中获取文档节点。"""
    if _index is not None and hasattr(_index, "docstore"):
        nodes = list(_index.docstore.docs.values())
        if nodes:
            return nodes

    if DATA_DIR.is_dir():
        documents = SimpleDirectoryReader(
            str(DATA_DIR), required_exts=[".txt"]
        ).load_data()
        if documents:
            return documents

    return []


def extract_node_text(node, max_len: int = 1500) -> str:
    """从节点对象提取文本内容。"""
    if hasattr(node, "text"):
        return node.text[:max_len]
    if hasattr(node, "get_content"):
        return node.get_content()[:max_len]
    return str(node)[:max_len]


def parse_qa_json(response_text: str) -> Optional[Dict[str, str]]:
    """从 LLM 响应中解析 QA JSON，兼容 markdown 代码块。"""
    code_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    candidates = [code_match.group(1)] if code_match else []
    candidates.append(response_text.strip())

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "question" in obj and "answer" in obj:
                return obj
        except json.JSONDecodeError:
            pass

    for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", response_text, re.DOTALL):
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict) and "question" in obj and "answer" in obj:
                return obj
        except json.JSONDecodeError:
            continue

    return None


# ============================================================
# RAGAS 适配器（按需加载）
# ============================================================
def get_ragas_models():
    """延迟初始化 RAGAS 所需的 LangChain 兼容模型。"""
    global _langchain_llm, _langchain_embeddings
    if _langchain_llm is not None:
        return _langchain_llm, _langchain_embeddings

    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models import BaseLLM
    from langchain_core.outputs import Generation, LLMResult
    from pydantic import PrivateAttr
    from ragas.llms import LangchainLLMWrapper

    api_key = require_api_key()

    class DashScopeLangChainLLM(BaseLLM):
        """将 DashScope LLM 适配为 LangChain BaseLLM，供 RAGAS 使用。"""

        model_name: str = "qwen-max"
        api_key: Optional[str] = None
        temperature: float = 0.1
        _dashscope_llm: Any = PrivateAttr()

        def __init__(
            self,
            model_name: str = "qwen-max",
            api_key: Optional[str] = None,
            temperature: float = 0.1,
        ):
            super().__init__(
                model_name=model_name,
                api_key=api_key or require_api_key(),
                temperature=temperature,
            )
            self._dashscope_llm = DashScope(
                model_name=model_name,
                api_key=self.api_key,
                temperature=temperature,
            )

        def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
            return str(self._dashscope_llm.complete(prompt))

        def _generate(
            self,
            prompts: List[str],
            stop: Optional[List[str]] = None,
            run_manager=None,
            **kwargs,
        ) -> LLMResult:
            generations = [
                [Generation(text=self._call(prompt, stop=stop))] for prompt in prompts
            ]
            return LLMResult(generations=generations)

        @property
        def _llm_type(self) -> str:
            return "dashscope"

        @property
        def _identifying_params(self) -> Mapping[str, Any]:
            return {"model_name": self.model_name, "temperature": self.temperature}

    class DashScopeLangChainEmbeddings(Embeddings):
        def __init__(
            self,
            model_name: str = DashScopeTextEmbeddingModels.TEXT_EMBEDDING_V1,
            api_key: Optional[str] = None,
        ):
            self._embed_model = DashScopeEmbedding(
                model_name=model_name,
                api_key=api_key or require_api_key(),
            )

        def embed_documents(self, texts: List[str]) -> List[List[float]]:
            return [self._embed_model.get_text_embedding(text) for text in texts]

        def embed_query(self, text: str) -> List[float]:
            return self._embed_model.get_query_embedding(text)

    eval_llm = DashScopeLangChainLLM(model_name="qwen-max", api_key=api_key, temperature=0.1)
    _langchain_llm = LangchainLLMWrapper(eval_llm)
    _langchain_embeddings = DashScopeLangChainEmbeddings(api_key=api_key)
    return _langchain_llm, _langchain_embeddings


# ============================================================
# 评估数据集与 RAG 预测
# ============================================================
def generate_evaluation_dataset(
    query_engine,
    num_questions: int = 10,
    output_path: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """从索引文档块自动生成 QA 评估对。"""
    _ = query_engine  # 确保调用方已加载引擎（索引随之就绪）
    output_path = Path(output_path or BASE_DIR / "eval_dataset.csv")

    nodes = get_index_nodes()
    if not nodes:
        logger.warning("无法获取文档节点，请检查 doc_emb 索引或 data 目录")
        return pd.DataFrame()

    selected_nodes = random.sample(nodes, min(num_questions, len(nodes)))
    eval_data = []

    qa_generation_prompt = """基于以下文本内容，生成一个相关的问答对。

文本内容：
{context}

请生成：
1. 一个与文本内容相关的问题
2. 该问题的标准答案（必须从文本中提取或推断）

仅输出 JSON，不要其他说明：
{{"question": "问题内容", "answer": "标准答案"}}
"""

    for i, node in enumerate(selected_nodes):
        context = extract_node_text(node)
        try:
            prompt = qa_generation_prompt.format(context=context)
            response_text = str(Settings.llm.complete(prompt))
            qa_pair = parse_qa_json(response_text)
            if qa_pair:
                eval_data.append(
                    {
                        "question": qa_pair.get("question", ""),
                        "ground_truth": qa_pair.get("answer", ""),
                        "context": context,
                    }
                )
                logger.info("生成第 %d 个 QA 对: %s...", i + 1, qa_pair.get("question", "")[:50])
            else:
                logger.warning("第 %d 个节点 JSON 解析失败，跳过", i + 1)
        except Exception as e:
            logger.error("生成 QA 对失败: %s", e)

    df = pd.DataFrame(eval_data)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info("评估数据集已保存到: %s (共 %d 条)", output_path, len(df))
    return df


def load_evaluation_dataset(dataset_path: Union[str, Path]) -> pd.DataFrame:
    """
    从 CSV 加载已有评估数据集。

    必需列：question
    标准答案列：ground_truth 或 answer（二选一）
    """
    path = Path(dataset_path)
    if not path.is_file():
        raise FileNotFoundError(f"评估数据集不存在: {path}")

    df = pd.read_csv(path, encoding="utf-8-sig")
    if "question" not in df.columns:
        raise ValueError(f"CSV 缺少 question 列: {path}")

    if "ground_truth" not in df.columns:
        if "answer" in df.columns:
            df = df.copy()
            df["ground_truth"] = df["answer"]
        else:
            raise ValueError(f"CSV 需包含 ground_truth 或 answer 列: {path}")

    df = df.dropna(subset=["question", "ground_truth"])
    df["question"] = df["question"].astype(str).str.strip()
    df["ground_truth"] = df["ground_truth"].astype(str).str.strip()
    df = df[(df["question"] != "") & (df["ground_truth"] != "")]

    if df.empty:
        raise ValueError(f"评估数据集无有效记录: {path}")

    return df


def run_rag_predictions(
    query_engine,
    questions: List[str],
    chunk_max_len: int = 500,
) -> Dict[str, List]:
    """
    对每个问题调用 RAG，返回答案和检索上下文。

    contexts 格式为 List[List[str]]，每个问题对应多个独立 chunk，符合 RAGAS 要求。
    """
    answers: List[str] = []
    contexts: List[List[str]] = []

    for i, question in enumerate(questions):
        logger.info("处理问题 %d/%d: %s...", i + 1, len(questions), question[:50])
        try:
            result = execute_rag_query(
                question, query_engine=query_engine, apply_security=False,
            )
            answers.append(result["answer"])
            src_snippets = [s.get("snippet", "") for s in result.get("sources", []) if s.get("snippet")]
            contexts.append([s[:chunk_max_len] for s in src_snippets])
        except Exception as e:
            logger.error("查询失败: %s", e)
            answers.append("")
            contexts.append([])

    return {"answer": answers, "contexts": contexts}


def normalize_contexts_for_ragas(contexts: List) -> List[List[str]]:
    """统一上下文格式为 RAGAS 所需的 List[List[str]]。"""
    if not contexts:
        return []
    if isinstance(contexts[0], str):
        return [[ctx] if ctx else [] for ctx in contexts]
    return contexts


def evaluate_with_ragas(
    questions: List[str],
    answers: List[str],
    contexts: List[List[str]],
    ground_truths: List[str],
):
    """使用 RAGAS 指标评估 RAG 输出。"""
    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import (
        AnswerCorrectness,
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )

    langchain_llm, langchain_embeddings = get_ragas_models()
    contexts_list = normalize_contexts_for_ragas(contexts)

    dataset = Dataset.from_dict(
        {
            "question": questions,
            "answer": answers,
            "contexts": contexts_list,
            "ground_truth": ground_truths,
        }
    )

    metrics = [
        Faithfulness(llm=langchain_llm),
        AnswerRelevancy(llm=langchain_llm),
        ContextPrecision(llm=langchain_llm),
        ContextRecall(llm=langchain_llm),
        AnswerCorrectness(llm=langchain_llm),
    ]

    logger.info("开始 RAGAS 评估...")
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=langchain_llm,
        embeddings=langchain_embeddings,
        raise_exceptions=False,
    )

    result_df = result.to_pandas() if hasattr(result, "to_pandas") else pd.DataFrame(result)
    return result, result_df


# ============================================================
# Gradio Web UI
# ============================================================
def _ensure_localhost_no_proxy() -> None:
    """确保本地地址不走 HTTP 代理，避免 Gradio 启动自检失败。"""
    bypass_hosts = ("127.0.0.1", "localhost")
    for key in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(key, "")
        hosts = [h.strip() for h in current.split(",") if h.strip()]
        for host in bypass_hosts:
            if host not in hosts:
                hosts.append(host)
        os.environ[key] = ",".join(hosts)


def _gradio_major_version() -> int:
    try:
        return int(gr.__version__.split(".")[0])
    except (ValueError, AttributeError):
        return 4


def _gradio_uses_messages_format() -> bool:
    """判断当前 Gradio 版本是否使用 messages 格式的 Chatbot。"""
    try:
        major, minor = (int(x) for x in gr.__version__.split(".")[:2])
        return (major, minor) >= (4, 0)
    except (ValueError, AttributeError):
        return False


def append_chat_history(history, user_msg: str, bot_msg: str):
    """兼容 Gradio 3.x（元组）与 4.x+（messages）两种 Chatbot 格式。"""
    history = history or []
    if _gradio_uses_messages_format():
        history.append({"role": "user", "content": user_msg})
        history.append({"role": "assistant", "content": bot_msg})
    else:
        history.append((user_msg, bot_msg))
    return history


def run_web_ui(server_port: int = 7860, server_name: str = "127.0.0.1"):
    """启动 Gradio Web 问答界面。"""
    _ensure_localhost_no_proxy()

    logger.info("正在加载 RAG 系统...")
    query_engine = get_query_engine()
    logger.info("RAG 系统已就绪，启动 Web UI...")

    def query_rag(message: str) -> str:
        if not message:
            return ""
        result = execute_rag_query(
            message, query_engine=query_engine, apply_security=True,
        )
        return format_answer_with_citations(result["answer"], result.get("sources", []))

    # Gradio 6.0+ 将 theme 移至 launch()，低版本仍在 Blocks() 中设置
    blocks_kwargs: Dict[str, Any] = {"title": "中医知识助手"}
    launch_kwargs: Dict[str, Any] = {
        "server_name": server_name,
        "server_port": server_port,
        "share": False,
    }
    if _gradio_major_version() >= 6:
        launch_kwargs["theme"] = gr.themes.Soft()
    else:
        blocks_kwargs["theme"] = gr.themes.Soft()

    with gr.Blocks(**blocks_kwargs) as demo:
        gr.Markdown("# 🌿 中医知识问答系统")
        gr.Markdown(
            "基于中医文档的检索增强生成系统，可回答中医证候相关问题。\n\n"
            f"> ⚠️ {DISCLAIMER}"
        )
        chatbot = gr.Chatbot(height=500)
        msg = gr.Textbox(
            label="请输入您的问题",
            placeholder="例如：不耐疲劳，口燥，咽干可能是哪些证候？",
        )
        clear = gr.ClearButton([msg, chatbot])

        def respond_and_update(message, chat_history):
            if not message:
                return "", chat_history
            bot_message = query_rag(message)
            chat_history = append_chat_history(chat_history, message, bot_message)
            return "", chat_history

        msg.submit(respond_and_update, [msg, chatbot], [msg, chatbot])

    demo.queue()
    logger.info("Web UI 地址: http://%s:%d", server_name, server_port)
    demo.launch(**launch_kwargs)


# ============================================================
# 评估主流程
# ============================================================
def _print_evaluation_results(questions: List[str], result_df: pd.DataFrame) -> Path:
    """打印评估汇总并保存详细结果 CSV。"""
    logger.info("=" * 60)
    logger.info("评估结果汇总")
    logger.info("=" * 60)

    for col in result_df.columns:
        if col in ("question", "answer", "contexts", "ground_truth"):
            continue
        numeric_col = pd.to_numeric(result_df[col], errors="coerce")
        mean_score = numeric_col.mean()
        if not pd.isna(mean_score):
            logger.info("%s: %.4f", col, mean_score)

    result_path = BASE_DIR / "ragas_evaluation_results.csv"
    result_df.to_csv(result_path, index=False, encoding="utf-8-sig")
    logger.info("详细评估结果已保存到: %s", result_path)

    metric_cols = [
        "faithfulness",
        "answer_relevancy",
        "context_precision",
        "context_recall",
        "answer_correctness",
    ]
    for i, question in enumerate(questions):
        row = result_df.iloc[i]
        logger.info("问题 %d: %s...", i + 1, question[:80])
        for metric in metric_cols:
            if metric in row:
                logger.info("  %s: %s", metric, row.get(metric, "N/A"))

    return result_path


def run_evaluation(
    num_questions: int = 10,
    dataset_path: Optional[Union[str, Path]] = None,
    eval_only: bool = False,
):
    """
    执行 RAGAS 评估流程。

    eval_only=False：生成 QA 对 → 跑 RAG → RAGAS 评估
    eval_only=True ：从已有 CSV 加载问题 → 跑 RAG → RAGAS 评估（跳过 QA 生成）
    """
    logger.info("=" * 60)
    logger.info("RAG 系统评估流程启动")
    logger.info("=" * 60)

    query_engine = get_query_engine()
    default_dataset = BASE_DIR / "rag_eval_dataset.csv"

    if eval_only:
        csv_path = Path(dataset_path) if dataset_path else default_dataset
        logger.info("步骤 1: 加载已有评估数据集（跳过 QA 生成）...")
        eval_df = load_evaluation_dataset(csv_path)
        logger.info("已加载 %s (共 %d 条)", csv_path, len(eval_df))
    else:
        logger.info("步骤 1: 生成评估数据集...")
        eval_df = generate_evaluation_dataset(
            query_engine,
            num_questions=num_questions,
            output_path=default_dataset,
        )
        if eval_df.empty:
            logger.error("未能生成有效的评估数据集，请检查文档内容")
            return

    questions = eval_df["question"].tolist()
    ground_truths = eval_df["ground_truth"].tolist()

    logger.info("步骤 2: 运行 RAG 系统获取预测结果...")
    predictions = run_rag_predictions(query_engine, questions)

    logger.info("步骤 3: 执行 RAGAS 评估...")
    _, result_df = evaluate_with_ragas(
        questions=questions,
        answers=predictions["answer"],
        contexts=predictions["contexts"],
        ground_truths=ground_truths,
    )

    _print_evaluation_results(questions, result_df)


# ============================================================
# Qwen-Agent 备选方案（可选依赖）
# ============================================================
try:
    from qwen_agent.agents import Agent
    from qwen_agent.llm.schema import Message

    class RAGAgent(Agent):
        """将 RAG 查询引擎封装为 Qwen-Agent（备选，当前主流程使用 Gradio）。"""

        def __init__(self, query_engine, **kwargs):
            super().__init__(**kwargs)
            self.query_engine = query_engine

        def _run(self, messages: List[Dict], **kwargs) -> Generator:
            def extract_text(content):
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if hasattr(item, "text"):
                            parts.append(item.text)
                        elif isinstance(item, dict) and "text" in item:
                            parts.append(item["text"])
                        elif isinstance(item, str):
                            parts.append(item)
                    return " ".join(parts)
                return str(content)

            last_msg = messages[-1] if messages else None
            user_query = ""
            if last_msg and last_msg.get("role") == "user":
                user_query = extract_text(last_msg.get("content", ""))

            if not user_query:
                yield [Message(role="assistant", content="请提出您的问题。", name=self.name)]
                return

            try:
                answer = str(self.query_engine.query(user_query))
                yield [Message(role="assistant", content=answer, name=self.name)]
            except Exception as e:
                yield [Message(role="assistant", content=f"处理问题时出错: {e}", name=self.name)]

except ImportError:
    Agent = None
    Message = None
    RAGAgent = None


# ============================================================
# 命令行入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="中医 RAG 系统")
    parser.add_argument("--eval", action="store_true", help="完整 RAGAS 评估（生成 QA + 评估）")
    parser.add_argument(
        "--eval-only",
        action="store_true",
        help="跳过 QA 生成，使用已有 CSV 运行 RAGAS 评估",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="评估数据集 CSV 路径（配合 --eval-only，默认 rag_eval_dataset.csv）",
    )
    parser.add_argument("--webui", action="store_true", help="启动 Web UI")
    parser.add_argument("--debug", action="store_true", help="开启 LlamaIndex 调试日志")
    parser.add_argument("--port", type=int, default=7860, help="Web UI 端口（默认 7860）")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Web UI 监听地址（默认 127.0.0.1；局域网访问用 0.0.0.0）",
    )
    parser.add_argument(
        "--num-questions", type=int, default=10, help="评估时生成的 QA 对数量（默认 10）"
    )
    args = parser.parse_args()

    if args.debug:
        os.environ["ZHONGYI_DEBUG"] = "1"

    try:
        if args.eval_only:
            run_evaluation(dataset_path=args.dataset, eval_only=True)
        elif args.eval:
            run_evaluation(num_questions=args.num_questions)
        else:
            run_web_ui(server_port=args.port, server_name=args.host)
    except EnvironmentError as e:
        logger.error(str(e))
        sys.exit(1)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
