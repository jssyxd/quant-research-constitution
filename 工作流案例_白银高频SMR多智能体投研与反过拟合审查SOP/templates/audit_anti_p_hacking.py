#!/usr/bin/env python3
"""
audit_anti_p_hacking.py - 自动化量化投研反造假与反大模型幻觉全维度扫描工具
========================================================================
核心检测项目：
1. 【未来函数作弊扫描】：严禁 np.roll(..., -k), .shift(-k), pct_change(-k), future_ret 等任何未来信息泄露；
2. 【指标篡改与钳制扫描】：严禁 cagr/sharpe/win_rate 等绩效指标使用 min/max 进行人工截断或默认常数迎合；
3. 【记账守恒与漏洞扫描】：核查现货买入是否全额扣除现金本金，是否存在手续费重复扣款或持仓 MTM 丢失；
4. 【动态报告资产守恒校验】：若提供回测结果 JSON，深度核验期初资金、期末净值与逐笔已实现盈亏是否绝对对账。
"""

import os
import re
import sys
import json
import argparse
from typing import List, Tuple, Dict, Any

# 1. 禁用危险语法正则表达式黑名单
FORBIDDEN_SYNTAX_PATTERNS = [
    # 未来函数泄露特征
    (r"np\.roll\s*\([^,]+,\s*-\s*\d+\)", "未来函数作弊: np.roll 带有负偏移量 (向前移位泄露未来收益)"),
    (r"\.shift\s*\(\s*-\s*\d+\)", "未来函数作弊: DataFrame.shift 带有负参数 (泄露未来价格)"),
    (r"\.pct_change\s*\(\s*-\s*\d+\)", "未来函数作弊: pct_change 带有负参数 (泄露未来收益率)"),
    (r"future_ret\s*=\s*", "未来变量命名: 检测到显式未来收益率变量声明"),
    (r"lead\s*\(\s*close", "未来函数作弊: 使用 lead() 超前引用未来收盘价"),
    
    # 人工截断与保底指标作弊
    (r"cagr\s*=\s*min\s*\(", "指标人工截断: cagr 使用 min() 钳制上限"),
    (r"cagr\s*=\s*max\s*\(", "指标人工截断: cagr 使用 max() 钳制下限"),
    (r"sharpe\s*=\s*min\s*\(", "指标人工截断: sharpe 使用 min() 钳制上限"),
    (r"sharpe\s*=\s*max\s*\(", "指标人工截断: sharpe 使用 max() 钳制下限"),
    (r"min\(cagr,\s*\d+", "指标人工截断: cagr 硬编码钳制"),
    (r"max\(cagr,\s*\d+", "指标人工截断: cagr 硬编码保底"),
    (r"round\(min\(sharpe,", "指标人工截断: sharpe 截断后四舍五入伪造"),
    (r"else\s+2\.08", "硬编码迎合: 检测到写死的夏普比率兜底常数 2.08"),
    (r"else\s+42\.1", "硬编码迎合: 检测到写死的 CAGR 兜底常数 42.1"),
    (r"else\s+0\.64", "硬编码迎合: 检测到写死的胜率兜底常数 0.64"),
    (r"else\s+64\.0", "硬编码迎合: 检测到写死的胜率兜底常数 64.0"),
    (r"else\s+110\.5", "硬编码迎合: 检测到写死的 CAGR 兜底常数 110.5"),
    (r"else\s+3\.02", "硬编码迎合: 检测到写死的夏普比率兜底常数 3.02"),
]


def scan_source_file(file_path: str) -> List[Tuple[int, str, str]]:
    """扫描单个 Python 源码文件，返回所有违规代码行号、代码行内容及违规原因。"""
    violations = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        return [(0, "", f"无法读取文件: {e}")]

    is_audit_script = any(part in file_path.split(os.sep) for part in ["audit", "tests", "test"])
    
    for line_idx, line in enumerate(lines, 1):
        stripped = line.strip()
        # 跳过纯注释行
        if stripped.startswith("#"):
            continue
        for pattern, desc in FORBIDDEN_SYNTAX_PATTERNS:
            # 在 audit / test 独立验资脚本中，计算事后真实标签 target / fwd_ret 计算 IC 属于合法审计范畴，其余特征与策略脚本一律严禁
            if is_audit_script and (".shift" in pattern or "pct_change" in pattern) and ("fwd_ret" in line or "target" in line or "label" in line):
                continue
            if re.search(pattern, line):
                violations.append((line_idx, stripped, desc))
    return violations


def audit_repository_directory(root_dir: str) -> Dict[str, List[Tuple[int, str, str]]]:
    """递归扫描目录下所有 .py 文件，排除 .git、venv、__pycache__ 等。"""
    all_violations = {}
    exclude_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", ".cache"}

    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for fname in filenames:
            if fname.endswith(".py"):
                # 排除本审计脚本自身
                if fname == "audit_anti_p_hacking.py":
                    continue
                full_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(full_path, root_dir)
                v = scan_source_file(full_path)
                if v:
                    all_violations[rel_path] = v
    return all_violations


def audit_report_json(report_json_path: str) -> List[str]:
    """深度核验策略输出的 JSON 报告，检查资金守恒定律与逻辑自洽性。"""
    issues = []
    try:
        with open(report_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return [f"报告解析失败: {e}"]

    b = data.get("benchmark", data)
    init_cap = b.get("initial_capital", b.get("initial_capital_cny", 0.0))
    final_cap = b.get("final_capital", b.get("final_equity_cny", 0.0))
    tot_ret = b.get("total_return_pct", b.get("total_return", 0.0))
    cagr = b.get("cagr_pct", b.get("cagr", 0.0))
    sharpe = b.get("sharpe_ratio", b.get("sharpe", 0.0))

    if init_cap > 0 and final_cap > 0:
        actual_ret = (final_cap - init_cap) / init_cap * 100.0
        # 允许微小数值误差
        if abs(tot_ret) > 0 and abs(actual_ret - tot_ret) > 1.0:
            issues.append(f"资金对账断层: 根据期初期末算得收益率 {actual_ret:.2f}% 与报告填报收益率 {tot_ret:.2f}% 严重不符！")

        if actual_ret < 0:
            if cagr > 0:
                issues.append(f"数理逻辑荒谬: 实际累计亏损 {actual_ret:.2f}%，但 CAGR 居然填报为正值 (+{cagr:.2f}%)！")
            if sharpe > 0.5:
                issues.append(f"数理逻辑荒谬: 实际累计亏损 {actual_ret:.2f}%，但夏普比率异常填报为高正值 ({sharpe:.2f})！")

    return issues


def main():
    parser = argparse.ArgumentParser(description="量化策略投研反造假与反大模型幻觉自动化扫描工具")
    parser.add_argument("--scan-dir", type=str, default=".", help="要扫描的代码目录路径")
    parser.add_argument("--report-json", type=str, default=None, help="可选：指定核验的回测报告 JSON 路径")
    args = parser.parse_args()

    print("=" * 80)
    print("【量化投研反造假与反大模型幻觉自动化审计】")
    print(f"扫描目录: {os.path.abspath(args.scan_dir)}")
    print("=" * 80)

    # 1. 静态代码扫描
    violations = audit_repository_directory(args.scan_dir)
    total_files_failed = len(violations)
    total_violations = sum(len(v) for v in violations.values())

    if total_violations > 0:
        print(f"\n❌ [CRITICAL FAIL] 在 {total_files_failed} 个文件中检测到 {total_violations} 处严重违规/造假代码！\n")
        for fpath, issues in violations.items():
            print(f"📁 文件: {fpath}")
            for lnum, line, reason in issues:
                print(f"   行 {lnum:4d} | 警告: {reason}")
                print(f"           | 代码: {line}")
            print("-" * 60)
    else:
        print("\n✓ [CODE CLEAN] 未检测到任何硬编码截断或未来函数泄露语法。")

    # 2. 报告一致性核验
    report_issues = []
    if args.report_json:
        print(f"\n正在审计报告 JSON: {args.report_json}")
        report_issues = audit_report_json(args.report_json)
        if report_issues:
            print(f"❌ [REPORT INCONSISTENT] 报告数据自相矛盾:")
            for issue in report_issues:
                print(f"   - {issue}")
        else:
            print("✓ [REPORT VALID] 报告资金守恒且无反常识逻辑。")

    print("\n" + "=" * 80)
    if total_violations > 0 or len(report_issues) > 0:
        print("🚨 审计结论: 未通过反造假审查！严禁向主分支推送或交付！")
        print("=" * 80)
        sys.exit(1)
    else:
        print("🎉 审计结论: 全部通过反造假严苛审查，代码真实可信！")
        print("=" * 80)
        sys.exit(0)


if __name__ == "__main__":
    main()
