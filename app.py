import streamlit as st

# --- 1. 避坑红线：全局常量定义 (必须在最顶层) ---
VERSION = "v6.9 (Hardened Final)"
STRATEGY_LIB = {
    "波动率专家": "专注于 IV 偏离，识别回归或突破时机。",
    "末日博弈": "聚焦高 Gamma，捕捉极速爆发收益。",
    "机构大单": "监控 OI/Vol 异动，识别主力新开仓信号。",
    "风险平价": "动态平衡仓位，维持组合生存力。"
}

# --- 2. UI 框架强制先行渲染 (解决白屏) ---
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

# --- 3. 核心初始化 (环境依赖) ---
import re, json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

def get_config(key):
    try: return os.environ.get(key) or st.secrets.get(key)
    except: return None

# 💡 同步附件：安全取值函数
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

# --- 4. 行情与决策逻辑 (Tiger-Eye Inside) ---
def fetch_intel(ticker, poly_client):
    try:
        tk = ticker.upper()
        snap = poly_client.get_snapshot_ticker("stocks", tk)
        prev = poly_client.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        
        lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
        tp = get_val(lt, 'p', 'price')
        mid_p = (get_val(lq, 'p', 'bid') + get_val(lq, 'P', 'ask')) / 2 if (get_val(lq, 'p', 'bid') > 0) else 0
        final_p = tp if tp > 0 else (mid_p if mid_p > 0 else y_close)
        
        # 抓取期权异动
        options = []
        try:
            chain = poly_client.list_snapshot_options_chain(tk, params={"strike_price.gte": final_p*0.9, "strike_price.lte": final_p*1.1, "limit": 8})
            for o in chain:
                vol, oi = get_val(o.day, 'volume'), get_val(o, 'open_interest')
                options.append({
                    "信号": "🔥新开仓" if (vol > oi and vol > 100) else "-",
                    "合约": o.details.ticker, "类型": o.details.contract_type,
                    "行权价": o.details.strike_price, "现价": get_val(o.day, 'c', 'close')
                })
        except: pass
        return {"ticker": tk, "price": final_p, "options": options, "source": "Trade" if tp > 0 else "Prev"}
    except: return {"ticker": ticker, "price": 0.0, "options": []}

def execute_worker(d, slot, clients):
    supabase, gen_client, poly = clients["supabase"], clients["gen_client"], clients["poly"]
    with slot:
        try:
            targets = d.get('portfolio') or ['GLD']
            trait = d.get('style') or "波动率专家"
            st.info(f"📡 **{d['name']} [{trait}] 穿透收集中...**")
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                intel = list(exe.map(lambda t: fetch_intel(t, poly), targets))
            
            valid_intel = {r['ticker']: r for r in intel if r['price'] > 0}
            if not valid_intel: st.error("❌ 行情中断"); return
            st.table(intel)

            # 敏捷研判
            prompt = f"你是一只{trait}工蜂。任务:基于行情{json.dumps(valid_intel)}和现金{d['balance']}做决策。只返回JSON:{{'thought':'中文','trades':[]}}"
            r = gen_client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]

            # 执行与日志 (patrol_count)
            nb, np, reports = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, act, qty = t.get('ticker','').upper(), t.get('action','').upper(), t.get('qty',0)
                px = valid_intel.get(sym, {}).get('price', 0)
                if px <= 0 or not act: continue
                cost = qty * px * (100 if len(sym) > 6 else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty; reports.append(f"买入 {sym}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty; reports.append(f"卖出 {sym}")
            
            mv = sum(q * fetch_intel(s, poly)['price'] for s, q in np.items() if len(s) < 10)
            res_msg = " | ".join(reports) if reports else "观望"
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {res_msg} | {decision.get('thought')}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            st.success(f"💭 {decision.get('thought')}")
        except Exception as e: st.error(f"失败: {e}")

# --- 5. UI 主逻辑 ---
clients, err = init_hive_engine()
if err: st.error(err); st.stop()

h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 个体特质基因已锁定 | 核心按钮持久化")
full_fly = h2.button("🚀 集群全量放飞", type="primary", use_container_width=True)

try:
    d_res = clients["supabase"].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 正在执行 {d['name']}...", expanded=True) as s:
            execute_worker(d, s, clients)
    st.success("✅ 放飞任务全部完成"); st.button("🔄 刷新"); st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("空。")
    for d in d_res:
        label = f"🐝 {d.get('name')} | {d.get('style','-')} | 资产: ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}"
        with st.expander(label):
            c1, c2 = st.columns(2)
            with c1: st.write(f"🧬 **基因:** {d.get('style', '波动率专家')}")
            with c2: st.write("**📦 持仓:**"); st.json(d.get('positions', {}))
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}"): execute_worker(d, st.container(), clients); st.rerun()
            for l in (d.get('logs') or [])[:3]: st.caption(l)

with tabs[1]:
    st.subheader("👑 蜂后孵化")
    trait = st.selectbox("注入核心特质:", list(STRATEGY_LIB.keys()))
    if st.button("🔥 孵化"):
        clients["supabase"].table("drones").insert({
            "name": f"工蜂-{random.randint(100,999)}", "style": trait,
            "balance": 100000.0, "total_assets": 100000.0, "patrol_count": 0,
            "portfolio": ["GLD"], "positions": {}, "logs": ["诞生于 v6.9"]
        }).execute(); st.rerun()

with tabs[2]:
    if st.button("🗑️ 清空所有数据"):
        clients["supabase"].table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()