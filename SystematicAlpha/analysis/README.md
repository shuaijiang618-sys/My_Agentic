# 人机研判工作区

本目录存放第 ④ 步产物，由 Cursor Agent 填写，Python 管道只读取、不生成。

## 目录约定

```
analysis/{run_id}/
├── analysis.json          # 结构化研判（风险维度、要点、图表配置）
└── narrative/
    ├── summary.md
    ├── financial_quality.md
    ├── risks.md
    └── conclusion.md
```

## 门禁

`make report` 或 `pipeline-report` 前须存在合法的 `analysis/{run_id}/analysis.json`。
