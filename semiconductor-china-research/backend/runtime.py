"""per-request 事件管道(实时把"谁在干什么"推给前端画动画)。

【为什么需要这一层】
一次 /api/run 的调用链很深:
    路由 → supervisor.run(MAF 内部) → 各专家工具 call_expert → web_search(ddgs)
最底层的 web_search 要把"开始检索 / 检索完成"实时告诉前端。如果靠函数参数一层层
往下传队列,既啰嗦、又侵入框架——supervisor.run 是 MAF 内部的,我们没法在它签名里塞参数。

【解法:contextvars】
contextvars 可理解为"协程安全的隐式全局变量":在请求入口 set 一次,同一异步调用树里
任意深度的函数都能 get 到,无需层层传参;且每个请求各有独立一份,并发互不串。
"""
import json
import time
import contextvars

# 本次请求的实时事件队列:各层把事件 put 进来,SSE 循环 get 出去边发给前端(见 server.py)
EVENT_Q = contextvars.ContextVar("event_q", default=None)
# 本次请求的起点(秒)。_ms() 用它算"距开始多少毫秒",前端据此画并行时间线
T0 = contextvars.ContextVar("t0", default=0.0)
# 本次请求里各专家检索命中的网页 {title, href},最后汇总成简报末尾的「参考来源」
SEARCH_LOG = contextvars.ContextVar("search_log", default=None)
# Phase 3 · 检索摘要文本(供事实校验)
SEARCH_SNIPPETS = contextvars.ContextVar("search_snippets", default=None)
# 每个专家整轮最多真检索 N 次
# 防"某维度本就无资料 → 反复重搜/重派"失控。{tag: {"n": 已搜次数, "last": 上次结果文本}}
SEARCH_BUDGET = contextvars.ContextVar("search_budget", default=None)
# 本轮各专家的完整结论 [{tool, output}]:supervisor 综合正文偶发缺失(pro 思考吃掉输出)时,
# server 用它做确定性兜底——把专家结论交给无工具的综合器强制再综合一次
EXPERT_RESULTS = contextvars.ContextVar("expert_results", default=None)


def _ms():
    """距本次请求开始的相对毫秒数 —— 每个事件都带它,前端靠它判断哪些步骤是并行的。"""
    return int((time.time() - T0.get()) * 1000)


def sse(event, data):
    """把一个事件序列化成一帧 SSE(Server-Sent Events)。

    SSE 是"服务器单向持续推消息给浏览器"的标准协议,格式固定:
        event: <事件名>\\n
        data:  <json>\\n
        \\n                 ← 空行表示一帧结束
    浏览器端用 `new EventSource(url)` + `addEventListener(事件名, ...)` 接收。
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
