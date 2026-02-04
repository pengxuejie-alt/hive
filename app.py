import streamlit as st
import re
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai
from polygon import RESTClient

# --- 1. 初始化 ---
st.set_page_config(page_title="Hive 蜂群系统", layout="wide")
st.title("🐝 Hive 蜂群生态系统")

def get_config(key): return os.environ.get(key) or st.secrets.get(key)

@st.cache_resource
def init_clients():
    try:
        return {
            "supabase": create_client(get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")),
            "gen_client": genai.Client(api_key=get_config("GEMINI_KEY")),
            "poly_client": RESTClient(api_key=get_config("POLYGON_KEY"))
        }
    except: return None

clients = init_clients()
if not clients: st.error("环境配置错误"); st.stop()
supabase, gen_client, poly_client = clients["supabase"], clients["gen_client"], clients["poly_client"]

# --- 2. 核心函数 ---
def fetch_nectar(ticker):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        px = getattr(sn, 'price', 0) or (getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') else getattr(sn.prev_day, 'c', 0))
        return {"代码": ticker, "现价": px}
    except: return {"代码": ticker, "现价": 0}

def execute_worker_cycle(d, slot):
    with slot:
        try:
            st.write("📡 **正在穿透行情...**")
            targets = d.get('portfolio', ['GLD'])
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_nectar, targets))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data)}。返回决策JSON。"
            r = gen_client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]

            nb, np, reports = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker', '').upper(), t.get('qty', 0), t.get('action', '').upper()
                px = fetch_nectar(sym)['现价']
                if px <= 0: continue
                cost = qty * px * (100 if ("O:" in sym or len(sym) > 6) else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym}@{px}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴卖出 {sym}@{px}")

            mv = sum(q * fetch_nectar(s)['现价'] * (100 if ("O:" in s or len(s) > 6) else 1) for s, q in np.items())
            total = round(nb + mv, 2)
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": total,
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "fitness_score": round((total / 100000.0) * 100, 2)
            }).eq("id", d["id"]).execute()
            
            st.success("✅ 放飞成功")
            time.sleep(1); st.rerun()
        except Exception as e: st.error(f"失败: {e}")

# --- 3. 首页 (找回一键放飞) ---
h1, h2 = st.columns([4, 1])
with h1: st.caption("Hive 蜂群系统 v5.4 | 经典回归")
full_fly = h2.button("🔥 一键放飞", type="primary", use_container_width=True) # 💡 按钮找回来了

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

# 处理全量放飞逻辑
if full_fly and d_res:
    for d in d_res: st.session_state[f"run_{d['id']}"] = True

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("档案库空。")
    else:
        for d in d_res:
            is_active = st.session_state.get(f"run_{d['id']}", False)
            # 💡 标题回归：去掉适应度，只显示资产和放飞次数
            label = f"🐝 {d.get('name')} | 资产: ${d.get('total_assets',0):,.2f} | 放飞: {d.get('patrol_count',0)}次"
            with st.expander(label, expanded=is_active):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"🧬 **基因:** {d.get('persona')}")
                    st.write(f"🧠 **记忆:** {d.get('memory', '初始')}")
                with c2:
                    st.write("**📦 持仓:**")
                    st.json(d.get('positions', {}))
                
                slot = st.container()
                if st.button(f"🚀 单独放飞", key=f"f_{d['id']}") or is_active: # 💡 文案改回来了
                    execute_worker_cycle(d, slot)
                    if is_active: st.session_state[f"run_{d['id']}"] = False
                    st.rerun()

with tabs[1]:
    st.subheader("👑 蜂后批量孵化")
    instr = st.text_area("指令 (如：孵化3只GLD工蜂):", value="孵化3只GLD工蜂")
    if st.button("🔥 执行孵化"):
        count = 1
        m = re.search(r'(\d+)只', instr)
        if m: count = int(m.group(1))
        with st.spinner(f"合成 {count} 只中..."):
            def spawn(i):
                p = f"设计JSON：{{'name':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}"
                res = gen_client.models.generate_content(model="gemini-2.0-flash", contents=p, config={'response_mime_type': 'application/json'})
                item = json.loads(res.text)
                if isinstance(item, list): item = item[0]
                new_drone = {
                    "name": f"{item.get('name', '工蜂')}-{random.randint(100,999)}",
                    "persona": item.get('persona', '初始'),
                    "balance": 100000.0, "total_assets": 100000.0, "initial_balance": 100000.0,
                    "patrol_count": 0, "positions": {}, "logs": ["诞生"],
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                supabase.table("drones").insert(new_drone).execute()
            with ThreadPoolExecutor(max_workers=count) as exe:
                exe.map(spawn, range(count))
            st.success("孵化完成"); time.sleep(1.5); st.rerun()

with tabs[2]:
    if st.button("🔥 清空数据"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()