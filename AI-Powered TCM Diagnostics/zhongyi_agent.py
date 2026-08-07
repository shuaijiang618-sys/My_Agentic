# -*- coding: utf-8 -*-
"""
中医知识问答系统 - 基于RAG（检索增强生成）的中医证候问答系统
功能：
1. 基于向量索引的问答（通过LlamaIndex + DashScope模型）
2. RAGAS评估框架自动评测（生成QA对并计算Faithfulness等指标）
3. Gradio Web界面（供用户交互）
4. 命令行参数控制：--webui启动界面，--eval运行评估
"""

import logging
import sys
import os
import random
import json
import re
import pandas as pd
import argparse
from typing import List, Dict, Any, Optional, Mapping, Generator
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    Faithfulness,
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    AnswerCorrectness
)
from ragas.llms import LangchainLLMWrapper
from langchain_core.outputs import Generation, LLMResult
from langchain_core.language_models import BaseLLM
from langchain_core.embeddings import Embeddings
from llama_index.core import (
    Settings, StorageContext, load_index_from_storage,
    PromptTemplate, SimpleDirectoryReader
)
from llama_index.llms.dashscope import DashScope, DashScopeGenerationModels
from llama_index.embeddings.dashscope import DashScopeEmbedding, DashScopeTextEmbeddingModels
from llama_index.core.callbacks import LlamaDebugHandler, CallbackManager
import warnings
warnings.filterwarnings('ignore')
import gradio as gr
# Qwen-Agent相关导入（仅用于备选方案，本系统实际使用Gradio直接构建界面）
from qwen_agent.agents import Agent
from qwen_agent.gui import WebUI

# ============================================================
# 1. 日志配置
# ============================================================
# 配置日志输出到标准输出，级别为INFO，便于观察系统运行状态
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
# 额外添加一个StreamHandler（通常basicConfig已添加，此行冗余但无害）
logging.getLogger().addHandler(logging.StreamHandler(stream=sys.stdout))

# ============================================================
# 2. 配置全局模型（DashScope）
# ============================================================
# 设置全局LLM：使用DashScope的Qwen-Max模型（需环境变量DASHSCOPE_API_KEY）
Settings.llm = DashScope(
    model_name=DashScopeGenerationModels.QWEN_MAX,
    api_key=os.getenv("DASHSCOPE_API_KEY")
)
# 设置全局Embedding模型：使用DashScope的文本嵌入V1
Settings.embed_model = DashScopeEmbedding(
    model_name=DashScopeTextEmbeddingModels.TEXT_EMBEDDING_V1
)

# 配置回调管理器，用于调试跟踪LlamaIndex内部事件
llama_debug = LlamaDebugHandler(print_trace_on_end=True)
callback_manager = CallbackManager([llama_debug])
Settings.callback_manager = callback_manager

# ============================================================
# 3. 定义 LangChain 适配器（让 RAGAS 能使用 DashScope LLM）
# ============================================================
class DashScopeLangChainLLM(BaseLLM):
    """
    将DashScope的LLM适配为LangChain的BaseLLM接口，供RAGAS使用。
    RAGAS需要LangChain风格的LLM来执行评估。
    """

    model_name: str = "qwen-max"
    api_key: Optional[str] = None
    temperature: float = 0.1

    def __init__(self, model_name: str = "qwen-max", api_key: Optional[str] = None, temperature: float = 0.1):
        # 调用父类BaseLLM的构造函数，确保基础属性正确初始化
        super().__init__()
        self.model_name = model_name
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.temperature = temperature
        # 内部维护DashScope原生LLM，实际调用通过它完成
        self._llm = DashScope(
            model_name=model_name,
            api_key=self.api_key,
            temperature=temperature
        )

    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        """单个prompt的调用，适配LangChain的_call接口"""
        response = self._llm.complete(prompt)
        return str(response)

    def _generate(
        self,
        prompts: List[str],
        stop: Optional[List[str]] = None,
        run_manager = None,
        **kwargs
    ) -> LLMResult:
        """批量prompt生成，必须实现以符合BaseLLM要求"""
        generations = []
        for prompt in prompts:
            text = self._call(prompt, stop=stop)
            generations.append([Generation(text=text)])
        return LLMResult(generations=generations)

    @property
    def _llm_type(self) -> str:
        """返回模型类型标识符，LangChain内部使用"""
        return "dashscope"

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        """返回用于唯一标识模型实例的参数"""
        return {"model_name": self.model_name, "temperature": self.temperature}

# ============================================================
# 4. 定义 LangChain 嵌入适配器（让 RAGAS 能使用 DashScope 嵌入）
# ============================================================
class DashScopeLangChainEmbeddings(Embeddings):
    """
    将DashScope的嵌入模型适配为LangChain的Embeddings接口。
    用于RAGAS评估中计算语义相似度等需要嵌入的指标。
    """
    def __init__(self, model_name: str = DashScopeTextEmbeddingModels.TEXT_EMBEDDING_V1, api_key: Optional[str] = None):
        self._embed_model = DashScopeEmbedding(
            model_name=model_name,
            api_key=api_key or os.getenv("DASHSCOPE_API_KEY")
        )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量嵌入文档"""
        embeddings = []
        for text in texts:
            emb = self._embed_model.get_text_embedding(text)
            embeddings.append(emb)
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """嵌入单个查询"""
        return self._embed_model.get_query_embedding(text)

# ============================================================
# 5. 创建 LangChain 兼容的 LLM 和嵌入实例（用于评估）
# ============================================================
# 创建适配器实例，然后包装为RAGAS可用的LangchainLLMWrapper
eval_llm = DashScopeLangChainLLM(model_name="qwen-max", temperature=0.1)
langchain_llm = LangchainLLMWrapper(eval_llm)   # RAGAS需要的包装器
# 创建嵌入适配器实例
langchain_embeddings = DashScopeLangChainEmbeddings()

# ============================================================
# 6. 加载持久化索引并构建查询引擎（全局对象）
# ============================================================
def load_query_engine():
    """
    加载之前持久化的向量索引（存储在doc_emb目录），并配置自定义提示模板，
    返回LlamaIndex的QueryEngine实例。
    """
    # 自定义系统提示（实际未直接使用，但为后续扩展保留）
    SYSTEM_PROMPT = """你是一位资深的中医专家，擅长辨证论治。你的任务是根据提供的上下文信息，准确回答用户关于中医证候的问题。"""

    # QA提示模板：结合上下文和用户问题，让模型基于上下文回答
    qa_prompt_tmpl_str = (
        "上下文信息如下：\n"
        "------------------\n"
        "{context_str}\n"
        "------------------\n"
        "请严格根据上述上下文信息回答以下问题。如果上下文中没有相关信息，请明确说明。\n"
        "问题：{query_str}\n"
        "回答："
    )
    qa_prompt_tmpl = PromptTemplate(qa_prompt_tmpl_str)

    # Refine提示模板：用于多文档逐步优化答案的场景
    refine_prompt_tmpl_str = (
        "原始问题：{query_str}\n"
        "现有答案：{existing_answer}\n"
        "补充上下文：\n"
        "----------------\n"
        "{context_msg}\n"
        "----------------\n"
        "请根据补充的上下文优化上述答案。如果补充上下文无帮助，返回原答案。\n"
        "优化后的答案："
    )
    refine_prompt_tmpl = PromptTemplate(refine_prompt_tmpl_str)

    # 从持久化目录加载索引
    storage_context = StorageContext.from_defaults(persist_dir="doc_emb")
    index = load_index_from_storage(storage_context)

    # 构建查询引擎，指定返回Top-K相似片段数
    query_engine = index.as_query_engine(
        similarity_top_k=5,
        streaming=False          # 非流式输出，简化
    )

    # 替换默认提示模板为自定义模板
    query_engine.update_prompts({
        "response_synthesizer:text_qa_template": qa_prompt_tmpl,
        "response_synthesizer:refine_template": refine_prompt_tmpl
    })

    print("✅ 查询引擎加载完成，自定义提示模板已应用")
    return query_engine

# 全局查询引擎实例（延迟加载，避免重复加载）
_query_engine = None

def get_query_engine():
    """获取全局查询引擎单例，延迟加载"""
    global _query_engine
    if _query_engine is None:
        _query_engine = load_query_engine()
    return _query_engine

# ============================================================
# 7. 生成评估数据集（QA对）
# ============================================================
def generate_evaluation_dataset(
        query_engine,
        num_questions: int = 10,
        output_path: str = "eval_dataset.csv"
) -> pd.DataFrame:
    """
    从现有文档中自动生成评估数据集（QA对）。
    策略：从索引中随机抽取文档块，让LLM根据该块生成问题和标准答案。
    """
    # 获取索引中的所有节点（文档块）
    storage_context = StorageContext.from_defaults(persist_dir="doc_emb")
    index = load_index_from_storage(storage_context)
    nodes = list(index.docstore.docs.values()) if hasattr(index, 'docstore') else []
    if not nodes:
        print("⚠️ 无法获取节点，尝试从索引中直接抽取...")
        documents = SimpleDirectoryReader("data", required_exts=['.txt']).load_data()
        nodes = documents

    # 随机选择指定数量的文档块
    selected_nodes = random.sample(list(nodes), min(num_questions, len(nodes)))
    eval_data = []

    # 提示模板：要求LLM根据文本生成QA对，并以JSON格式输出
    qa_generation_prompt = """
    基于以下文本内容，生成一个相关的问答对。

    文本内容：
    {context}

    请生成：
    1. 一个与文本内容相关的问题
    2. 该问题的标准答案（必须从文本中提取或推断）

    输出格式（JSON）：
    {{"question": "问题内容", "answer": "标准答案"}}

    注意：问题应具有实际意义，答案应简洁准确。
    """

    for i, node in enumerate(selected_nodes):
        # 提取节点文本（限制长度，避免超出上下文窗口）
        if hasattr(node, 'text'):
            context = node.text[:1500]
        elif hasattr(node, 'get_content'):
            context = node.get_content()[:1500]
        else:
            context = str(node)[:1500]

        try:
            prompt = qa_generation_prompt.format(context=context)
            response = Settings.llm.complete(prompt)
            response_text = str(response)
            # 从响应中提取JSON（简单正则匹配）
            json_match = re.search(r'\{[^{}]*"question"[^{}]*"answer"[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                qa_pair = json.loads(json_match.group())
                eval_data.append({
                    "question": qa_pair.get("question", ""),
                    "ground_truth": qa_pair.get("answer", ""),
                    "context": context
                })
                print(f"✅ 生成第 {i+1} 个 QA 对: {qa_pair.get('question', '')[:50]}...")
            else:
                print(f"⚠️ 第 {i+1} 个节点解析失败，跳过")
        except Exception as e:
            print(f"❌ 生成 QA 对失败: {e}")
            continue

    df = pd.DataFrame(eval_data)
    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"\n✅ 评估数据集已保存到: {output_path} (共 {len(df)} 条)")
    return df

# ============================================================
# 8. 运行 RAG 系统获取预测结果
# ============================================================
def run_rag_predictions(
        query_engine,
        questions: List[str]
) -> Dict[str, List[str]]:
    """
    对每个问题调用RAG系统，返回生成的答案和检索到的上下文（用于后续评估）。
    """
    answers = []
    contexts = []
    for i, question in enumerate(questions):
        print(f"处理问题 {i+1}/{len(questions)}: {question[:50]}...")
        try:
            response = query_engine.query(question)
            answers.append(str(response))
            # 提取检索到的片段（仅保留前500字符用于评估）
            if hasattr(response, 'source_nodes'):
                retrieved_contexts = [node.node.get_content()[:500] for node in response.source_nodes]
                contexts.append("\n\n".join(retrieved_contexts))
            else:
                contexts.append("")
        except Exception as e:
            print(f"❌ 查询失败: {e}")
            answers.append("")
            contexts.append("")
    return {"answer": answers, "contexts": contexts}

# ============================================================
# 9. 使用 RAGAS 进行评估
# ============================================================
def evaluate_with_ragas(
        questions: List[str],
        answers: List[str],
        contexts: List[List[str]],
        ground_truths: List[str]
) -> Dict[str, Any]:
    """
    使用RAGAS指标对RAG系统的输出进行评估。
    """
    # 转换上下文格式：RAGAS要求每个问题的contexts是一个列表（即使只有一个上下文）
    contexts_list = [[ctx] for ctx in contexts] if isinstance(contexts[0], str) else contexts

    data = {
        "question": questions,
        "answer": answers,
        "contexts": contexts_list,
        "ground_truth": ground_truths
    }
    dataset = Dataset.from_dict(data)

    # 实例化评估指标，并传入LangChain兼容的LLM
    metrics = [
        Faithfulness(llm=langchain_llm),
        AnswerRelevancy(llm=langchain_llm),
        ContextPrecision(llm=langchain_llm),
        ContextRecall(llm=langchain_llm),
        AnswerCorrectness(llm=langchain_llm)
    ]

    print("\n📊 开始 RAGAS 评估...")
    print("=" * 60)

    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=langchain_llm,          # 全局LLM（指标内部也会使用）
        embeddings=langchain_embeddings,   # 嵌入模型
        raise_exceptions=False
    )

    # 将评估结果转为DataFrame便于查看
    if hasattr(result, 'to_pandas'):
        result_df = result.to_pandas()
    else:
        result_df = pd.DataFrame(result)

    return result, result_df

# ============================================================
# 10. Qwen-Agent 自定义 Agent（封装 RAG 系统）[备选方案]
# ============================================================
# 尝试导入Qwen-Agent相关模块，如果失败则设置标志位为None
try:
    from qwen_agent.agents import Agent
    from qwen_agent.gui import WebUI
    from qwen_agent.llm.schema import Message
except ImportError:
    print("⚠️ 请安装 qwen-agent 和 gradio: pip install qwen-agent gradio")
    Agent = None
    WebUI = None
    Message = None

if Agent is not None:
    class RAGAgent(Agent):
        """将RAG查询引擎封装为Qwen-Agent，用于Web UI（备选，当前未使用）"""
        def __init__(self, query_engine, **kwargs):
            super().__init__(**kwargs)
            self.query_engine = query_engine

        def _run(self, messages: List[Dict], **kwargs) -> Generator:
            # 安全提取文本的辅助函数
            def extract_text(content):
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    texts = []
                    for item in content:
                        if hasattr(item, 'text'):
                            texts.append(item.text)
                        elif isinstance(item, dict) and 'text' in item:
                            texts.append(item['text'])
                        elif isinstance(item, str):
                            texts.append(item)
                    return ' '.join(texts)
                else:
                    return str(content)

            # 获取最后一条用户消息
            last_msg = messages[-1] if messages else None
            if last_msg and last_msg.get('role') == 'user':
                user_query = extract_text(last_msg.get('content', ''))
            else:
                user_query = ''

            if not user_query:
                yield [Message(role='assistant', content='请提出您的问题。', name=self.name)]
                return

            try:
                response = self.query_engine.query(user_query)
                answer = str(response)
                yield [Message(role='assistant', content=answer, name=self.name)]
            except Exception as e:
                yield [Message(role='assistant', content=f"处理问题时出错: {e}", name=self.name)]

# ============================================================
# 11. Web UI 启动函数（基于 Gradio）
# ============================================================
def run_web_ui():
    """使用 Gradio 构建简洁的 Web 问答界面，供用户与 RAG 系统交互。"""
    print("正在加载 RAG 系统...")
    query_engine = get_query_engine()
    print("✅ RAG 系统已就绪，启动 Web UI...")

    def respond(message, history):
        """处理用户消息，返回RAG系统的回答"""
        if not message:
            return ""
        try:
            response = query_engine.query(message)
            return str(response)
        except Exception as e:
            return f"处理问题时出错: {e}"

    # 创建 Gradio 界面（使用 Blocks 实现自定义布局）
    with gr.Blocks(title="中医知识助手", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🌿 中医知识问答系统")
        gr.Markdown("基于中医文档的检索增强生成系统，可回答中医证候相关问题。")
        chatbot = gr.Chatbot(height=500)        # 聊天历史显示组件
        msg = gr.Textbox(label="请输入您的问题", placeholder="例如：不耐疲劳，口燥，咽干可能是哪些证候？")
        clear = gr.ClearButton([msg, chatbot])  # 清空输入框和聊天记录

        def respond_and_update(message, chat_history):
            if not message:
                return "", chat_history
            bot_message = respond(message, chat_history)
            chat_history.append((message, bot_message))
            return "", chat_history

        # 绑定事件：用户按回车提交问题
        msg.submit(respond_and_update, [msg, chatbot], [msg, chatbot])
        # 清空按钮点击事件（ClearButton已自动清空，此处额外调用lambda无副作用）
        clear.click(lambda: None, None, chatbot, queue=False)

    demo.queue()   # 启用队列以支持并发
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)

# ============================================================
# 12. 评估主流程（原 main 函数）
# ============================================================
def run_evaluation():
    """
    执行完整的 RAGAS 评估流程：
    1. 生成评估数据集（QA对）
    2. 运行RAG系统获得预测结果
    3. 使用RAGAS计算各项指标并保存结果
    """
    print("=" * 60)
    print("🔍 RAG 系统评估流程启动")
    print("=" * 60)

    print("\n📝 步骤 1: 生成评估数据集...")
    eval_df = generate_evaluation_dataset(
        get_query_engine(),
        num_questions=10,
        output_path="rag_eval_dataset.csv"
    )

    if len(eval_df) == 0:
        print("❌ 未能生成有效的评估数据集，请检查文档内容")
        return

    questions = eval_df["question"].tolist()
    ground_truths = eval_df["ground_truth"].tolist()

    print("\n🚀 步骤 2: 运行 RAG 系统获取预测结果...")
    predictions = run_rag_predictions(get_query_engine(), questions)

    print("\n📈 步骤 3: 执行 RAGAS 评估...")
    result, result_df = evaluate_with_ragas(
        questions=questions,
        answers=predictions["answer"],
        contexts=predictions["contexts"],
        ground_truths=ground_truths
    )

    print("\n" + "=" * 60)
    print("📊 评估结果汇总")
    print("=" * 60)

    # 计算各指标平均分
    metrics_scores = {}
    for col in result_df.columns:
        if col in ['question', 'answer', 'contexts', 'ground_truth']:
            continue
        try:
            numeric_col = pd.to_numeric(result_df[col], errors='coerce')
            mean_score = numeric_col.mean()
            if not pd.isna(mean_score):
                metrics_scores[col] = mean_score
                print(f"{col}: {mean_score:.4f}")
            else:
                print(f"⚠️ 列 '{col}' 全部为空，跳过")
        except Exception as e:
            print(f"⚠️ 列 '{col}' 无法转换为数值: {e}")

    # 保存详细结果
    result_df.to_csv("ragas_evaluation_results.csv", index=False, encoding='utf-8-sig')
    print(f"\n✅ 详细评估结果已保存到: ragas_evaluation_results.csv")

    print("\n📋 各问题详细评分:")
    print("=" * 80)
    for i, (question, row_tuple) in enumerate(zip(questions, result_df.iterrows())):
        _, row_data = row_tuple
        print(f"\n问题 {i+1}: {question[:80]}...")
        faithfulness_val = row_data.get('faithfulness', 'N/A')
        answer_relevancy_val = row_data.get('answer_relevancy', 'N/A')
        context_precision_val = row_data.get('context_precision', 'N/A')
        context_recall_val = row_data.get('context_recall', 'N/A')
        answer_correctness_val = row_data.get('answer_correctness', 'N/A')
        print(f"忠实度: {faithfulness_val}")
        print(f"答案相关性: {answer_relevancy_val}")
        print(f"上下文精确度: {context_precision_val}")
        print(f"上下文召回率: {context_recall_val}")
        print(f"答案正确性: {answer_correctness_val}")
        print("-" * 40)

# ============================================================
# 13. 命令行入口
# ============================================================
if __name__ == "__main__":
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description="中医 RAG 系统")
    parser.add_argument("--eval", action="store_true", help="运行 RAGAS 评估")
    parser.add_argument("--webui", action="store_true", help="启动 Web UI")
    args = parser.parse_args()

    # 根据参数选择模式，默认启动Web UI（无参数时）
    if args.eval:
        run_evaluation()
    elif args.webui:
        run_web_ui()
    else:
        run_web_ui()