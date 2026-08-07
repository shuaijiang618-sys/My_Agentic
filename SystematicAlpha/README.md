# A股年报本地量化投研系统

基于 **A 股上市公司年度报告 PDF** 的本地投研流水线：从巨潮资讯等渠道获取年报，自动解析三大财务报表、计算关键指标、生成图表，并结合 Agent 人机研判输出可离线打开的 HTML 投研报告。

**设计原则**

| 角色 | 职责 |
|------|------|
| **Python 管道** | 确定性工作：PDF 接入、表格解析、科目映射、指标计算、出图、HTML 汇编。**不调用 LLM API** |
| **Cursor Agent** | 财务研判：风险维度评分、跨表验证结论、叙事章节，落盘为 `analysis/` 下的 JSON 与 Markdown |

---

## 流水线概览

```
PDF（data/input/）
    │
    ▼
① ingest      校验 PDF、提取元数据、归档 source.pdf
    │
    ▼
② parse       按锚点抽取文本与三大表 raw_tables
    │
    ▼
③ normalize   科目映射 → financials.json，会计恒等式自检
    │
    ▼
④ metrics     15 项财务指标 → metrics.json
    │
    ▼
⑤ analysis    【门禁】Agent 研判 → analysis.json / cross_validation.json / narrative/
    │
    ▼
⑥ visualize   matplotlib 生成 14 张 PNG（base64 可内嵌报告）
    │
    ▼
⑦ report      Jinja2 汇编 → reports/{run_id}_report.html
```

一键入口：

```bash
python -m quant_research.cli run "宁德时代2025年年度报告.pdf"
```

---

## 目录结构

```
AI量化投研系统/
├── config/                 # 可配置规则（YAML）
│   ├── table_anchors.yaml      # 三大表 PDF 定位锚点
│   ├── account_mapping.yaml    # 科目别名 → 标准 key
│   ├── section_anchors.yaml    # 章节切分锚点
│   └── report_sections.yaml    # HTML 报告章节顺序
├── schemas/                # JSON Schema 契约
│   ├── manifest.schema.json
│   ├── financials.schema.json
│   ├── metrics.schema.json
│   └── analysis.schema.json
├── data/
│   ├── input/                  # 待分析 PDF（*.pdf 默认 gitignore）
│   ├── runs/{run_id}/          # 单次运行产物（中间数据 + 图表）
│   └── {run_id}_*.json         # 部分结果的便捷副本
├── analysis/{run_id}/      # 人机研判工作区（Agent 写入）
│   ├── analysis.json
│   ├── cross_validation.json
│   └── narrative/*.md
├── reports/                # 最终 HTML 报告
├── templates/
│   └── report.html.j2
├── src/quant_research/     # Python 包
│   ├── cli.py                  # Typer CLI
│   ├── ingest/                 # PDF 接入
│   ├── parse/                  # 文本 / 表格抽取
│   ├── normalize/              # 三表标准化与校验
│   ├── metrics/                # 指标计算
│   ├── visualize/              # 图表生成
│   ├── report/                 # HTML 汇编
│   ├── orchestration/          # 流水线编排
│   └── common/                 # IO、路径、元数据
├── tests/                  # pytest 测试
├── scripts/                # 契约校验等脚本
└── requirements.txt
```

---

## 各阶段产物

### `data/runs/{run_id}/`

| 文件 | 说明 |
|------|------|
| `manifest.json` | 公司名、报告年份、SHA256、页数等元数据 |
| `source.pdf` | 归档的原始 PDF |
| `raw_pages.json` | 逐页纯文本 |
| `raw_tables.json` | 三大表原始行列 |
| `raw_sections.json` | 按章节切分的文本块 |
| `financials.json` | 标准化三表（current / prior，单位统一为**元**） |
| `balance_check.json` | 会计恒等式自检结果 |
| `metrics.json` | 15 项财务指标及公式、输入溯源 |
| `charts/*.png` | 可视化图表 |
| `charts_manifest.json` | 图表清单 |

### `analysis/{run_id}/`

| 文件 | 说明 |
|------|------|
| `analysis.json` | 综合风险等级、7 维风险评分、红旗信号、图表覆盖配置 |
| `cross_validation.json` | 三表勾稽通过项、口径差异、增速背离告警 |
| `narrative/*.md` | 投资摘要、财务质量、风险因素、结论等叙事章节 |

### `reports/`

| 文件 | 说明 |
|------|------|
| `{run_id}_report.html` | 自包含 HTML（内嵌 CSS + base64 图表），浏览器直接打开 |

---

## 快速开始

### 1. 环境

```bash
cd "AI量化投研系统"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src
export MPLCONFIGDIR="$(pwd)/.mplconfig"   # matplotlib 缓存，避免权限问题
```

### 2. 放入年报 PDF

将 PDF 放到 `data/input/`，例如：

- `宁德时代2025年年度报告.pdf`
- `比亚迪2025年年度报告.pdf`

也可传入绝对路径，或在 `data/` 下递归按文件名查找。

### 3. 一键全流程

```bash
python -m quant_research.cli run "比亚迪2025年年度报告.pdf"
# 或显式指定 run_id
python -m quant_research.cli run "宁德时代2025年年度报告.pdf" --run-id catl_2025
```

`run_id` 默认由公司名 + 报告年份推导（如 `宁德时代` → `catl_2025`，`300750_2025半年报.pdf` → `300750_2025`）。

### 4. 分步执行

```bash
python -m quant_research.cli ingest   catl_2025 "data/input/xxx.pdf"
python -m quant_research.cli parse    catl_2025
python -m quant_research.cli normalize catl_2025
python -m quant_research.cli metrics  catl_2025
# ← 此处由 Agent 完成 analysis/{run_id}/ 研判
python -m quant_research.cli visualize catl_2025
python -m quant_research.cli report   catl_2025
```

组合命令：

```bash
python -m quant_research.cli pipeline-data   catl_2025 "xxx.pdf"   # ①→④
python -m quant_research.cli pipeline-report catl_2025             # ⑥→⑦
```

### 5. 打开报告

```bash
open reports/catl_2025_report.html
open reports/byd_2025_report.html
```

---

## 研判门禁

Python **不会**自动生成 `analysis.json`。`run` / `report` / `pipeline-report` 在第 ⑤ 步检查：

```
analysis/{run_id}/analysis.json
```

若缺失，数据管道（①–④）仍会完成，流程暂停并提示：

```
⏸ ⑤ 研判门禁 — 缺少研判文件
请由 Agent 完成 analysis.json 后，执行:
python -m quant_research.cli pipeline-report {run_id}
```

研判内容规范见 [`analysis/README.md`](analysis/README.md)。

---

## 核心模块说明

### ingest — PDF 接入

- 使用 **PyMuPDF** 探测页数、抽样文本、是否可提取文字
- 从首页 / 文件名启发式提取：公司名、股票代码、报告年份、报告类型
- 复制 PDF 到 `data/runs/{run_id}/source.pdf`，写入 `manifest.json`

### parse — 解析

- **pdfplumber** 按 `table_anchors.yaml` 定位合并资产负债表 / 利润表 / 现金流量表
- 锚点匹配要求关键词与 `start_row_markers`（如「流动资产」「营业收入」）**同页共现**，避免误匹配审计报告中的「合并资产负债表」字样
- 支持两种版式：
  - **网格表**（如宁德时代）：pdfplumber 直接抽表
  - **竖排表**（如比亚迪）：科目名单独成行、金额在后续行，走 `_parse_vertical_financial_text` 回退解析
- 输出 `raw_pages.json`、`raw_tables.json`、`raw_sections.json`

### normalize — 标准化

- `account_mapping.yaml` 将「货币资金」「营业收入」等别名映射为标准 key
- 自动识别报表单位（元 / 千元 / 万元），统一换算为**元**
- 行级金额解析，兼容 pdfplumber 列偏移
- `balance_check.json` 校验：`资产总计 = 负债合计 + 所有者权益合计`（本期、上期）

### metrics — 指标

基于 `financials.json` 确定性计算 **15 项指标**（能算多少算多少）：

| 类别 | 指标 |
|------|------|
| 偿债能力 | 资产负债率、产权比率、流动比率、速动比率、现金比率 |
| 盈利能力 | 毛利率、营业利润率、净利率、ROE、ROA |
| 现金流 | 经营现金流/净利润、经营现金流/营收 |
| 营运能力 | 应收周转率、存货周转率、总资产周转率 |

每项含 `value`、`value_prior`、`formula`、`inputs`，便于审计与报告展示。

### visualize — 可视化

matplotlib 生成 **14 张 PNG**，包括：

- 关键指标六宫格趋势（营收、净利润、经营现金流、存货、应收、毛利率）
- 盈利能力、营运资本、收入结构、资产负债结构
- 偿债能力、现金流量、风险雷达图（需 `analysis.json` 中的 `chart_overrides`）

图表写入 `data/runs/{run_id}/charts/`，HTML 报告以 base64 内嵌，无需外部图片文件。

### report — HTML 报告

- Jinja2 模板 `templates/report.html.j2` + `report/assets/style.css`
- 章节：投资摘要 → 财务概览 KPI → 关键指标表 → 三表勾稽 → 图表 → 风险因素 → 财务质量叙事 → 结论
- 读取 `config/report_sections.yaml` 决定叙事 Markdown 的嵌入顺序
- 输出到 `reports/{run_id}_report.html`

---

## 配置说明

### `config/table_anchors.yaml`

每种报表的配置项：

- `keywords`：标题关键词（如「合并资产负债表」）
- `start_row_markers` / `end_row_markers`：表体起止行
- `stop_page_markers`：跨页扫描终止标记（如「2、合并利润表」）
- `exclude`：排除母公司报表等干扰

### `config/account_mapping.yaml`

标准科目 key 与 A 股常见别名列表。新增公司若有个别科目命名差异，在此补充别名即可，无需改代码。

---

## 已验证案例

| 公司 | run_id | 报告年份 | 特点 |
|------|--------|----------|------|
| 宁德时代 | `catl_2025` | 2025 | 网格表版式；15/15 指标可算；存货 vs 成本背离研判 |
| 比亚迪 | `byd_2025` | 2025 | 竖排表版式；13/15 指标可算；增收不增利、OCF 走弱 |

PDF 可从 [巨潮资讯](http://www.cninfo.com.cn/) 下载，例如比亚迪 2025 年报：  
`https://static.cninfo.com.cn/finalpage/2026-03-28/1225045351.PDF`

---

## 测试

```bash
export PYTHONPATH=src
export MPLCONFIGDIR="$(pwd)/.mplconfig"
pytest tests/ -q
```

| 测试文件 | 覆盖 |
|----------|------|
| `test_ingest_parse.py` | PDF 接入与解析 |
| `test_normalize.py` | 标准化与恒等式 |
| `test_metrics.py` | 指标计算 |
| `test_visualize.py` | 图表生成 |
| `test_report.py` | HTML 报告 |
| `test_full_pipeline.py` | 端到端流水线 |

---

## 扩展与定制

1. **新公司 / 新科目**：编辑 `config/account_mapping.yaml`
2. **特殊 PDF 版式**：调整 `table_anchors.yaml`，或在 `parse/pdf_tables.py` 增强竖排 / 回退解析
3. **新增指标**：在 `metrics/calculators.py` 注册，并更新 `schemas/metrics.schema.json`
4. **新增图表**：在 `visualize/key_charts.py` 或 `charts.py` 添加函数，并在 `generate_charts` 中注册
5. **报告样式**：修改 `report/assets/style.css` 与 `templates/report.html.j2`
6. **研判模板**：按 `analysis/README.md` 约定扩展 `analysis.json` 字段与 narrative 章节

---

## 已知限制

- **趋势图仅两期**：单份年报只有本期 / 上期，「趋势图」实为同比柱形对比；多年折线需 ingest 多期 PDF
- **研判依赖 Agent**：无 `analysis.json` 时无法生成完整报告（风险雷达、叙事章节）
- **PDF 版式差异**：极端扫描件、图片型 PDF 需 OCR（当前未集成）
- **股票代码**：部分 PDF 元数据提取为 `null`，可后续完善 `common/metadata.py` 或 manifest 手工修正
- **归母 vs 合并净利润**：部分公司利润表科目命名不一，可能与公开「归母净利润」存在口径差

---

## 技术栈

| 用途 | 库 |
|------|-----|
| PDF 文本 | PyMuPDF (fitz) |
| PDF 表格 | pdfplumber |
| CLI | Typer |
| 图表 | matplotlib |
| 报告 | Jinja2 + Markdown |
| 校验 | jsonschema |
| 测试 | pytest |

---

## 许可证与免责声明

本项目仅供**本地研究与学习**使用。HTML 报告页脚已注明：不构成投资建议。年报数据以上市公司法定披露文件为准。
