# --- 1. 神经中枢：2026 官方标准模型 ID ---
# 优先级：2.5-flash (极速) -> 2.0-flash (稳定) -> 3-flash-preview (前沿)
BRAIN_POOL = [
    "gemini-2.5-flash", 
    "gemini-2.0-flash", 
    "gemini-2.0-flash-001",
    "gemini-3-flash-preview"
]

@st.cache_resource
def get_working_brain():
    """实战探测：确保模型名在当前 API Key 下真实可用"""
    gk = os.environ.get("GEMINI_KEY") or st.secrets.get("GEMINI_KEY")
    client = genai.Client(api_key=gk)
    for model_id in BRAIN_POOL:
        try:
            # 发起一个最简单的内容生成测试
            client.models.generate_content(model=model_id, contents="test")
            return model_id
        except Exception:
            continue
    return "gemini-1.5-flash" # 最后的最后，尝试老版本兼容名

# 锁定当前真实可用的大脑
ACTIVE_BRAIN = get_working_brain()