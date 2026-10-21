import re

for p in [
    '/home/da/桌面/strategy/007_eth_ai_timing_alphaevolve/CONVERSATION_HISTORY.md',
    '/home/da/桌面/quant-research-constitution/工作流案例_ETH_AI_AlphaEvolve符号演化与伪Q-Learning逆向投研SOP/CONVERSATION_HISTORY.md'
]:
    with open(p, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 遮蔽 HuggingFace token 与 Kaggle token
    content = re.sub(r'hf_[a-zA-Z0-9]{34}', 'hf_**********************************', content)
    content = re.sub(r'KGAT_[a-zA-Z0-9]{32}', 'KGAT_********************************', content)
    content = re.sub(r'ghp_[a-zA-Z0-9]{36}', 'ghp_************************************', content)
    
    with open(p, 'w', encoding='utf-8') as f:
        f.write(content)

print("敏感 Token 脱敏完成！")
