import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 核心配置与初始化 ---
VERSION = "v3.7 (Stable Cluster)"
ACTIVE_BRAIN = "gemini-2.0-flash" 

def get_config(key): return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    G_KEY, P_KEY = get_config("GEMINI_KEY"), get_config("POLYGON_KEY")
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
except Exception as e:
    st.error(f"❌ 初始化失败: {e}"); st.stop()

# --- 2. 神经调度引擎 (防熔断与唯一性增强) ---
def safe_brain_decision(prompt):
    for attempt in range(3):
        try:
            time.sleep(random.uniform(0.1, 0.4))
            r = gen_client.models.generate_content(
                model=ACTIVE_BRAIN, 
                contents=prompt, 
                config={'response_mime_type': 'application/json'}
            )
            data = json.loads(r.text)
            return data[0] if isinstance(data, list) else data
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                time.sleep((attempt + 1) * 2)
                continue
            raise e

def fetch_nectar(ticker):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        price = getattr(sn, 'price', 0) or (getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') else getattr(sn.prev_day, 'c', 0))
        return {"代码": ticker, "现价": price, "涨跌%": round(getattr(sn, 'todays_change_percent', 0), 2)}
    except: return {"代码": ticker, "现价": 0}

# --- 3. 演化执行逻辑 ---
def execute_worker_cycle(d, status_container):
    try:
        with status_container:
            st.write("📡 **采集行情...**")
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_nectar, d.get('portfolio', ['GLD'])))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            st.json(nectar_data)

            st.write(f"🧠 **神经研判 (`{ACTIVE_BRAIN}`)...**")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data, ensure_ascii=False)}。返回指令JSON。"
            decision = safe_brain_decision(prompt)

            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker', t.get('symbol', '')).upper(), t.get('qty', 0), t.get('action', '').upper()
                px = fetch_nectar(sym)['现价']
                cost = float(qty) * float(px) * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴卖出 {sym}")

            mv = sum(q * fetch_nectar(s)['现价'] * (100 if "O:" in s else 1) for s, q in np.items())
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')}"] + (d.get('logs') or []))[:20]
            }).eq("id", d["id"]).execute()
            st.success("✅ 演化完成")
    except Exception as e:
        status_container.error(f"❌ 运行崩溃: {str(e)}")

# --- 4. 主界面布局 ---
st.set_page_config(page_title="Hive 蜂群系统", layout="wide")

h1, h2 = st.columns([4, 1])
with h1:
    st.title(f"🐝 Hive 蜂群生态系统 `{VERSION}`")
    st.caption(f"🧠 中枢: `{ACTIVE_BRAIN}` | 🛡️ 状态: 付费带宽正常")
with h2:
    st.write(" ")
    full_fly = st.button("🔥 全量放飞", type="primary", use_container_width=True)

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data
if full_fly and d_res:
    for d in d_res: st.session_state[f"run_{d['id']}"] = True

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

# --- TAB 0: 档案 ---
with tabs[0]:
    if not d_res: st.info("请先孵化工蜂。")
    for d in (d_res or []):
        is_active = st.session_state.get(f"run_{d['id']}", False)
        with st.expander(f"🐝 {d['name']} | 资产: ${d['total_assets']:,.2f}", expanded=is_active):
            slot = st.container()
            if st.button(f"🚀 立即放飞", key=f"f_{d['id']}") or is_active:
                execute_worker_cycle(d, slot)
                if is_active: st.session_state[f"run_{d['id']}"] = False
                st.rerun()
            st.json(d.get('positions', {}))
            for l in (d.get('logs') or [])[:5]: st.caption(l)

# --- TAB 1: 孵化 (3变2修复版) ---
with tabs[1]:
    st.subheader("👑 蜂后集群孵化")
    c1, c2 = st.columns([3, 1])
    instr = c1.text_area("孵化指令:", value="孵化3只德州之神项目工蜂")
    count = c2.number_input("数量", 1, 10, 3)
    
    if st.button("🔥 启动集群孵化"):
        with st.spinner(f"🧬 正在合成 {count} 个生命特征..."):
            def spawn_one(idx):
                seed = random.randint(1000, 9999)
                p = f"设计JSON：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}。唯一编号：{idx}-{seed}"
                try:
                    time.sleep(idx * 0.3)
                    item = safe_brain_decision(p)
                    # 💡 强行增加后缀，防止重名导致 Supabase 判定为重复行
                    item['name'] = f"{item.get('name', '工蜂')}_{idx}_{seed}"
                    item.update({
                        "balance": 100000.0, "total_assets": 100000.0, 
                        "created_at": datetime.now(timezone.utc).isoformat(), 
                        "logs": ["诞生"], "positions": {}
                    })
                    supabase.table("drones").insert(item).execute()
                    return item['name']
                except: return None

            with ThreadPoolExecutor(max_workers=count) as exe:
                names = list(exe.map(spawn_one, range(count)))
            st.success(f"✅ 成功孵化: {', '.join(filter(None, names))}")
            time.sleep(1); st.rerun()

# --- TAB 2: 管理 ---
with tabs[2]:
    if st.button("🔥 清空蜂巢"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()