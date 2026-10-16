# 投研委托任务书模板 (Task Brief Template)

```markdown
# [阶段编号] [任务名称] 委托任务书

- **执行智能体**: [如: data-governor / quant-engineer / pi-auditor]
- **所属项目与路径**: [如: to-research/008_doge_momentum]
- **底层模型底座**: [如: cpa/claude-sonnet-4-6]
- **任务目标**: [1-2句话明确该阶段的具体计算与工程目标]

---

## 一、物理数据输入契约 (Input Data Contracts)
- 数据源文件路径: [绝对路径 / URL]
- 数据时间跨度: [起止日期与时间戳]
- 数据字段完整性要求: [必须包含的字段]
- 前置合规检查: [是否通过因果无未来函数扫描]

---

## 二、工作标准与实现约束 (Engineering Constraints)
1. 算法逻辑实现边界: [说明所采用的具体数学公式与物理机制]
2. 记账守恒原则: [现货必须全额扣款，合约必须核算 MMR]
3. 严禁行为黑名单: [严禁 min/max 截断，严禁 roll(-k)，严禁虚构成交流水]

---

## 三、下游交付物与卡点验收标准 (Deliverable Quality Gates)
1. 代码输出文件: [路径]
2. 逐笔成交流水 CSV: [路径与字段对账标准]
3. 必须通过的量化检验指标:
   - Walk-Forward 效率: WFE >= 60.0%
   - 1000次蒙特卡洛 VaR 95% 回撤 <= 阈值
   - 自动化反造假 CI 扫描: 0 违规
```
