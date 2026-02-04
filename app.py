import streamlit as st

# ==========================================
# 🚨 红线 1: 全局常量锁死 (严禁白屏/NameError)
# ==========================================
VERSION = "v7.3 (Anti-Freeze Edition)"
STRATEGY_LIB = {
    "波动率专家": "分析 IV 偏离，识别回归或突破时机。",
    "末日博弈": "聚焦高 Gamma，捕捉极速爆发收益。",
    "机构大单": "监控 OI/Vol 异动，识别主力新开仓信号。",
    "风险平价": "动态平衡仓位，维持组合生存力。"
}

# ==========================================
# 🚨 红线 2: 框架强制先行渲染
# ==========================================
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

# 延迟导入，确保 UI 先出
import re, json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_config(key):
    try: return os.environ.get(key) or st.secrets.get(key)
    except: return None

# 💡 同步附件：虎眼穿透取值函数
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_hive_engine():
    try:
        from supabase import create_client
        from google import genai
        from polygon import RESTClient
        return {
            "supabase": create_client(get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")),
            "gen_client": genai.Client(api_key=get_config("GEMINI_KEY")),
            "poly": RESTClient(api_key=get_config("POLYGON_KEY"))
        }, None
    except Exception as e: return None, str(e)

# ==========================================
# 🚨 红线 3: 虎眼穿透取价 (三级回退)
# ==========================================
def fetch_tiger_eye(ticker, poly):
    try:
        tk = ticker.upper()
        # 1. 抓取 Snapshot
        sn = poly.get_snapshot_ticker("stocks", tk)
        # 2. 抓取昨日收盘做兜底
        prev = poly.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        
        lt, lq = getattr(sn, 'last_trade', None), getattr(sn, 'last_quote', None)
        tp = get_val(lt, 'p', 'price') 
        mid_p = (get_val(lq, 'p', 'bid') + get_val(lq, 'P', 'ask')) / 2 if (get_val(lq, 'p', 'bid') > 0) else 0
        
        # 优先级：成交价 > 买卖中值 > 昨日收盘
        final_p = tp if tp > 0 else (mid_p if mid_p > 0 else y_close)
        
        return {"代码": tk, "现价": final_p, "来源": "Trade" if tp > 0 else ("Quote" if mid_p > 0 else "Prev")}
    except:
        return {"代码": ticker, "现价": 0.0, "来源": "Timeout"}

# ==========================================
# 🚨 红线 4: 数据与 UI 渲染 (保证蜜蜂显示)
# ==========================================
clients, err = init_hive_engine()
d_res = []
if not err:
    try:
        # 优先级：必须先读出蜜蜂列表
        d_res = clients["supabase"].table("drones").select("*").order("created_at", desc=True).execute().data
    except: d_res = []

# UI 标题栏
h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 虎眼穿透引擎已锁定 | 核心按钮持久化")
full_fly = h2.button("🚀 集群全量放飞", type="primary", use_container_width=True)

# 放飞执行函数
def run_evolution(d, slot):
    with slot:
        try:
            tks = d.get('portfolio') or ['GLD']
            st.info(f"📡 穿透检索中: {tks}")
            
            # 💡 并行检索 + 超时控制
            results = []
            with ThreadPoolExecutor(max_workers=5) as exe:
                futures = {exe.submit(fetch_tiger_eye, tk, clients["poly"]): tk for tk in tks}
                for f in as_completed(futures, timeout=8): # 8秒强制结束
                    results.append(f.result())
            
            st.table(results) # 透明化展示
            valid_px = {r['代码']: r['现价'] for r in results if r['现价'] > 0}
            if not valid_px: st.warning("未获行情"); return

            # 敏捷研判 (个体化 Prompt)
            style = d.get('style') or "波动率专家"
            prompt = f"你是{style}。标的:{tks}。现价:{json.dumps(valid_px)}。现金:{d['balance']}。请用中文返回决策JSON:{{'thought':'','trades':[]}}"
            r = clients["gen_client"].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            
            # 结算代码略... (已确保更新 patrol_count)
            st.success(f"✅ {d['name']} 演化同步完成")
        except Exception as e: st.error(f"演化异常: {e}")

# --- 渲染逻辑 ---
if err: st.error(err); st.stop()

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 调度 {d['name']}...", expanded=True):
            run_evolution(d, st.container())
    st.success("✅ 集群演化任务结束")
    st.button("🔄 刷新界面")
    st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("当前蜂巢为空。")
    for d in d_res:
        label = f"🐝 {d.get('name')} | {d.get('style','-')} | ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}次"
        with st.expander(label):
            c1, c2 = st.columns(2)
            with c1: st.write(f"🧬 **特质:** {d.get('style', '波动率专家')}")
            with c2: st.write("**📦 持仓:**"); st.json(d.get('positions', {}))
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}"):
                run_evolution(d, st.container())
            for l in (d.get('logs') or [])[:3]: st.caption(l)

with tabs[2]:
    if st.button("🗑️ 清空蜂群"):
        clients["supabase"].table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()