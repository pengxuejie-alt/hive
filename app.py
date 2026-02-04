import streamlit as st
import re, json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai  # 💡 修正：回退到你环境中正确的库
from polygon import RESTClient

# --- 1. 配置与初始化 (架构加固) ---
st.set_page_config(page_title="Hive 智能金融", layout="wide")
VERSION = "v6.4 (Dependency Fixed)"

def get_config(key):
    try: return os.environ.get(key) or st.secrets.get(key)
    except: return None

# 💡 安全数值提取逻辑
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_clients():
    try:
        pk, gk = get_config("POLYGON_KEY"), get_config("GEMINI_KEY")
        su, sk = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
        if not all([pk, gk, su, sk]): return None, "⚠️ 配置缺失，请检查 Secrets"
        return {
            "supabase": create_client(su, sk),
            "poly": RESTClient(api_key=pk),
            "gen_client": genai.Client(api_key=gk) # 💡 修正写法
        }, None
    except Exception as e: return None, str(e)

cl_pkg, err = init_clients()
if err: st.error(err); st.stop()
supabase, poly_client, gen_client = cl_pkg["supabase"], cl_pkg["poly"], cl_pkg["gen_client"]

# --- 2. 虎眼级行情穿透引擎 ---
def fetch_data_tiger_eye(ticker):
    try:
        tk = ticker.upper()
        # 同步附件：Snapshot + Previous Close 兜底
        snap = poly_client.get_snapshot_ticker("stocks", tk)
        prev = poly_client.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        
        lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
        tp = get_val(lt, 'p', 'price') 
        bp = get_val(lq, 'p', 'bid')
        ap = get_val(lq, 'P', 'ask')
        mid_p = (bp + ap) / 2 if (bp > 0 and ap > 0) else 0
        
        # 优先级：成交 > 买卖中值 > 昨日收盘
        final_p = tp if tp > 0 else (mid_p if mid_p > 0 else y_close)
        
        return {"代码": tk, "现价": final_p, "来源": "Trade" if tp > 0 else ("Quote" if mid_p > 0 else "Prev")}
    except: return {"代码": ticker, "现价": 0.0, "来源": "Error"}

# --- 3. 演化核心逻辑 ---
def execute_worker_cycle(d, slot):
    with slot:
        try:
            targets = d.get('portfolio') or ['GLD'] 
            st.write(f"📡 **情报穿透中: {targets}**")
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_data_tiger_eye, targets))
            
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            st.table(results)

            if not nectar_data:
                st.error("❌ 穿透失败：未能获取任何行情。")
                return

            st.write("🧠 **中枢研判中...**")
            prompt = f"分析标的 {targets}。资产: 现金 ${d['balance']}, 持仓 {json.dumps(d.get('positions'))}。情报: {json.dumps(nectar_data)}。用中文写思考过程并返回决策JSON:{{'thought':'','trades':[],'learning':''}}"
            
            # 💡 修正：使用 google-genai 的调用方式
            r = gen_client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=prompt,
                config={'response_mime_type': 'application/json'}
            )
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]

            st.success(f"💭 思考逻辑: {decision.get('thought')}")

            # 交易结算
            nb, np, reports = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym = t.get('ticker', '').upper()
                px = nectar_data.get(sym, {}).get('现价', 0)
                if px <= 0: continue
                cost = t.get('qty', 0) * px * (100 if len(sym) > 6 else 1)
                if t['action'] == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + t['qty']; reports.append(f"买入 {sym}@{px}")
                elif t['action'] == 'SELL' and np.get(sym, 0) >= t['qty']:
                    nb += cost; np[sym] -= t['qty']; reports.append(f"卖出 {sym}@{px}")
                    if np[sym] <= 0: del np[sym]

            mv = sum(q * nectar_data.get(s, {}).get('现价', 0) for s, q in np.items())
            rep = " | ".join(reports) if reports else "观望"
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {rep} | {decision.get('thought')}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            
            st.write(f"📝 **结果: {rep}**")
        except Exception as e: st.error(f"❌ 执行异常: {e}")

# --- 4. UI 界面 ---
h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 穿透引擎已就绪")
full_fly = h2.button("🚀 一键全量放飞", type="primary", use_container_width=True)

try:
    d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 调度 {d['name']}...", expanded=True) as s:
            execute_worker_cycle(d, s)
    st.success("✅ 集群放飞完成"); st.button("刷新"); st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])
with tabs[0]:
    if not d_res: st.info("空。")
    for d in d_res:
        with st.expander(f"🐝 {d.get('name')} | 资产: ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}"):
            c1, c2 = st.columns(2)
            with c1: st.write(f"🧬 **基因:** {d.get('persona')}")
            with c2: st.write("**📦 持仓:**"); st.json(d.get('positions', {}))
            if st.button(f"🚀 单独放飞", key=f"r_{d['id']}"):
                execute_worker_cycle(d, st.container())
            for l in (d.get('logs') or [])[:3]: st.caption(l)

with tabs[1]:
    st.subheader("👑 蜂后孵化")
    if st.button("🔥 孵化测试工蜂"):
        supabase.table("drones").insert({
            "name": f"量化员-{random.randint(100,999)}", "persona": "稳健型",
            "balance": 100000.0, "total_assets": 100000.0, "patrol_count": 0,
            "portfolio": ["GLD"], "positions": {}, "logs": ["诞生"]
        }).execute(); st.rerun()

with tabs[2]:
    if st.button("🗑️ 清空所有数据"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()