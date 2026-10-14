# 案例二 · 模块四：Credal Transformer 反过拟合审查与 NautilusTrader 回测引擎

> **定位**: 严禁过拟合幻觉的数理审查体系与纳秒级事件驱动回测实现  
> **理论基石**: NeurIPS 2025 Credal Transformer (ArXiv:2510.12137) ｜ DSR (Bailey & López de Prado)

---

## 1. Credal Transformer 狄利克雷证据不确定性门控

传统机器学习模型输出单一的 Softmax 概率，极易产生**“高置信度幻觉（Overconfident Hallucination）”**——即在面对无信息的随机盘口噪点时，强行输出 0.99 的多头概率。Credal Transformer 引入主观逻辑（Subjective Logic），将模型预测转化为狄利克雷分布的不确定性集合（Credal Set）。

### 1.1 数学公式与物理推导

设系统将多因子特征映射为三向证据向量：$[e_{\text{bull}}, e_{\text{bear}}, e_{\text{neutral}}]$。
对应狄利克雷超参数 $\alpha_k = e_k + 1.0$，全证据总量 $S$ 与信念守恒满足：
$$S = \sum_{k=1}^3 \alpha_k = e_{\text{bull}} + e_{\text{bear}} + e_{\text{neutral}} + 3.0$$
$$b_k = \frac{e_k}{S}, \quad u = \frac{K}{S} = \frac{3}{S}$$
$$b_{\text{bull}} + b_{\text{bear}} + b_{\text{neutral}} + u = 1.0$$

- **$u \in [0, 1]$：认知不确定性 / 证据真空度（Vacuity Uncertainty）**。当证据匮乏时，$S \to 3$，$u \to 1.0$；
- **$C \in [0, 1]$：多空方向冲突度（Directional Conflict Mass）**：
  $$C = \frac{2 \cdot \min(b_{\text{bull}}, b_{\text{bear}})}{b_{\text{bull}} + b_{\text{bear}}}$$

### 1.2 宪法级放行准则（Credal Execution Gate）
策略引擎在处理任意入场脉冲前，必须调用 [`credal_smr_audit.py`](./code/credal_smr_audit.py) 中的 `evaluate_evidence`。**只要触发下列任一条件，必须立即弃权（Abstain），拒绝报单**：
1. **$u > 0.35$**：证据真空度超标，拒绝在缺乏统计显著性的噪点区间开仓；
2. **$C \ge 0.40$**：多空因子剧烈对冲冲突，判定为虚假突破/洗盘；
3. **$\max(p_{\text{bull}}, p_{\text{bear}}) < 0.50$**：预期胜率概率优势不明显。

---

## 2. 通缩夏普比率 (DSR) 与 Harvey-Liu 发型扣减

在经过多轮因子挑选与参数回测后，名义夏普比率（Nominal Sharpe）存在严重的选优偏差。系统引入双重统计修正：

### 2.1 通缩夏普比率（Deflated Sharpe Ratio, DSR）
根据 *Bailey & López de Prado (2014)*，在 $N = 100$ 次独立参数试验下，零技能空假设下期望的最大夏普为：
$$\mathbb{E}[\max_{n=1\dots N} SR_n] \approx (1 - \gamma) \Phi^{-1}\left(1 - \frac{1}{N}\right) + \gamma \Phi^{-1}\left(1 - \frac{1}{N e}\right)$$
实测计算得：**$\mathbb{E}[\max SR] = 2.53$**。
- 只有当实际策略夏普经过非正态偏度、峰度修正后，超越 $2.53$ 的后验概率 **$P(SR > \mathbb{E}[\max SR]) \ge 95\%$** 时，策略方可通过 DSR 审计。

### 2.2 Harvey-Liu 发型夏普扣减（Haircut Sharpe）
根据 *Harvey & Liu (2015)*，根据数据开采程度对夏普比率进行发型扣减：
$$\text{Haircut Ratio} = \max\left(0.0, \ 1.0 - \frac{\mathbb{E}[\max SR]}{|SR_{\text{est}}| + \epsilon}\right)$$
$$\text{Haircut } SR = SR_{\text{est}} \times \text{Haircut Ratio}$$

---

## 3. 蒙特卡洛 1,000 次净值路径置换检验 (Monte Carlo Test)

为了检验实测收益是源自**稳定的时间序列因果边缘（True Alpha Edge）**还是**偶发的幸运成交次序（Path Luck）**，系统对成交记录执行 1,000 次无放回随机置换（Permutation Test）：

```
[原始交易收益序列: R_1, R_2, ... R_M]
                 │
                 ├───> 随机打乱序列顺序 (Permutation 1 ... 1000)
                 │           │
                 │           ▼
                 │     重新构建 1,000 条蒙特卡洛合成净值曲线
                 │           │
                 ▼           ▼
        [实际观测 Sharpe] vs [置换 Sharpe 分布] ──► 计算经验显著性 p-value
                             [最差 95% 回撤分布] ──► 计算极端路径压力边界
```

---

## 4. NautilusTrader 原生事件驱动策略设计

在 [`nautilus_silver_smr.py`](./code/nautilus_silver_smr.py) 中，策略完全封装为 NautilusTrader 1.221.0 标准类：

```python
from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

class NautilusSilverSMRConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    initial_cash: float = 100_000.0
    risk_pct: float = 0.50                 # 0.50% 动态风险预算 (复利模型)
    maker_fee: float = 0.0002              # 2 bps 真实 Maker 费率
    taker_fee: float = 0.0005              # 5 bps 真实 Taker 费率
    slippage: float = 0.0005               # 5 bps 悲观滑点
    max_notional_cap: float = 11_000_000.0 # 8000 万 CNY 容量上限 (~11M USDT)
    use_credal_gate: bool = True           # 启用 Credal Transformer 门控
```

### 关键工程约束
1. **纯前向流动状态机**：所有技术指标与 Credal 决策必须基于已收盘的历史 Bar 计算；
2. **悲观成交假设**：限价单挂单只在下一根 Bar 的极值穿越限价时撮合，止损单必须承担 Taker 费率与滑点惩罚；
3. **资金池动态复利**：每笔交易风险金额严格绑定当前账户实时净值（`Equity * risk_pct`），当净值回撤时仓位自动等比例下调防守。
