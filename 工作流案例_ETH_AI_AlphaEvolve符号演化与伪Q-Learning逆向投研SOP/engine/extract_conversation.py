import json

session_path = '/home/da/.pi/agent/sessions/--home-da-桌面-ethAI--/2026-10-19T13-51-32-673Z_01a1546e-893f-744e-b005-a868dd6b7701.jsonl'

lines = []
with open(session_path, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            data = json.loads(line)
            lines.append(data)
        except:
            pass

md_output = """# [月读量化] ETH AI 择时策略 (AlphaEvolve GP + Q-State) 全程投研与工程落地完整对话记录

> **会话时间**: 2026-10-19 至 2026-10-20  
> **记录说明**: 本文档记录了本交易程序从第三方信号黑箱逆向解构、开源代码扒取、真实数据湖治理、15m 遗传规划演化重构、双引擎逐笔回测验证，到 AI 哨兵监控、CI/CD 自动化流水线设计及量化宪法建立的全程原始真实对话记录。

---

"""

turn_idx = 1
for item in lines:
    # 查找 user 或 assistant 消息
    msg_type = item.get('type')
    if msg_type == 'message':
        msg = item.get('message', {})
        role = msg.get('role')
        content = msg.get('content', '')
        
        if role == 'user':
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get('type') == 'text':
                        text += part.get('text', '') + "\n"
                    elif isinstance(part, str):
                        text += part + "\n"
            
            # 过滤掉系统内部自动发出的纯指令或空消息，保留核心对话
            if text.strip():
                md_output += f"\n## 👤 用户提问 (Round {turn_idx})\n\n{text.strip()}\n\n---\n"
                
        elif role == 'assistant':
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get('type') == 'text':
                        text += part.get('text', '') + "\n"
                    elif isinstance(part, str):
                        text += part + "\n"
            
            if text.strip():
                md_output += f"\n## 🤖 AI 智能体回答 (Round {turn_idx})\n\n{text.strip()}\n\n---\n"
                turn_idx += 1

output_file_strat = '/home/da/桌面/strategy/007_eth_ai_timing_alphaevolve/CONVERSATION_HISTORY.md'
output_file_const = '/home/da/桌面/quant-research-constitution/工作流案例_ETH_AI_AlphaEvolve符号演化与伪Q-Learning逆向投研SOP/CONVERSATION_HISTORY.md'

with open(output_file_strat, 'w', encoding='utf-8') as f:
    f.write(md_output)

with open(output_file_const, 'w', encoding='utf-8') as f:
    f.write(md_output)

print(f"成功导出完整对话记录！共计 {turn_idx-1} 轮完整交互。")
