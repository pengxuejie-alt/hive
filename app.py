import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 环境初始化 ---
VERSION = "v4.2 (Real-time Sync)"
ACTIVE_BRAIN = "gemini-2.0-flash"

def get_config(key): return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    G_KEY, P_KEY = get_config("GEMINI_KEY"), get_config("POLYGON_KEY")
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
except Exception as e:
    st.error(f"❌ 蜂巢启动失败: {e}"); st.stop()

# --- 2. 大脑与行情 ---
def safe_brain_decision(prompt):
    for attempt in range(3):
        try:
            time.sleep(0.2)
            r = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=prompt, config={'response_mime_type': 'application/json'})
            data = json.loads(r.text)
            return data[0] if isinstance(data, list) else data
        except Exception as e:
            if "429" in str(e): time.sleep(2); continue
            raise e

def fetch_nectar(ticker):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        price = getattr(sn, 'price', 0) or (getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') else getattr(sn.prev_day, 'c', 0))
        return {"代码": ticker, "现价": price}
    except: return {"代码": ticker, "现价": 0}

# --- 3. 演化核心 ---
def execute_worker_cycle(d, slot):
    with slot:
        try:
            st.write("📡 **多源行情采集...**")
            targets = d.get('portfolio', ['SPY', 'QQQ'])
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_nectar, targets))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            st.info(f"📊 行情透传: {json.dumps(nectar_data)}")

            st.write("🧠 **神经元决策中...**")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。记忆:{d.get('memory','无')}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data)}。返回JSON决策。"
            decision = safe_brain_decision(prompt)

            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker', '').upper(), t.get('qty', 0), t.get('action', '').upper()
                px = fetch_nectar(sym)['现价']
                if px <= 0: continue
                cost = qty * px * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym}@{px}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴卖出 {sym}@{px}")

            mv = sum(q * fetch_nectar(s)['现价'] * (100 if "O:" in s else 1) for s, q in np.items())
            log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')} | 🧠 {decision.get('thought','')}"
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([log_entry] + (d.get('logs') or []))[:20],
                "memory": decision.get('learning', d.get('memory')),
                "fly_count": (d.get('fly_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            st.success("✅ 演化记录更新成功")
        except Exception as e:
            st.error(f"❌ 运行失败: {e}")

# --- 4. UI 界面 ---
st.set_page_config(page_title="Hive 蜂群系统", layout="wide")

# 标题栏
h1, h2 = st.columns([4, 1])
h1.title(f"🐝 Hive 蜂群生态系统 `{VERSION}`")
full_fly = h2.button("🔥 全量放飞", type="primary", use_container_width=True)

# 💡 强制从数据库获取最新列表
@st.fragment
def load_drones():
    return supabase.table("drones").select("*").order("created_at", desc=True).execute().data

d_res = load_drones()

if full_fly and d_res:
    for d in d_res: st.session_state[f"run_{d['id']}"] = True

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res:
        st.info("蜂巢空空如也，请点击“蜂后孵化”页签。")
    else:
        for d in d_res:
            is_active = st.session_state.get(f"run_{d['id']}", False)
            label = f"🐝 {d['name']} | 资产: ${d['total_assets']:,.2f} | 次数: {d.get('fly_count',0)}"
            with st.expander(label, expanded=is_active):
                c_info, c_data = st.columns([1, 1])
                with c_info:
                    st.markdown(f"**🧬 基因:** {d.get('persona', '初始')}\n\n**🧠 记忆:** {d.get('memory', '无')}")
                with c_data:
                    st.write("**📦 持仓 JSON:**")
                    st.json(d.get('positions', {}))
                
                slot = st.container()
                if st.button(f"🚀 立即演化", key=f"btn_{d['id']}") or is_active:
                    execute_worker_cycle(d, slot)
                    if is_active: st.session_state[f"run_{d['id']}"] = False
                    st.rerun()
                for l in (d.get('logs') or [])[:3]: st.caption(l)

with tabs[1]:
    st.subheader("👑 集群孵化中心")
    c1, c2 = st.columns([3, 1])
    instr = c1.text_area("孵化基因指令:", value="德州之神项目，赌场高手风格")
    count = c2.number_input("数量", 1, 10, 3)
    
    if st.button("🔥 开始大规模孵化"):
        with st.spinner("正在并发合成生命特征..."):
            def spawn(idx):
                p = f"设计JSON：{{'name':'3字中文名','logic':'','persona':'','portfolio':['GLD']}}。内容中文。指令：{instr}"
                try:
                    item = safe_brain_decision(p)
                    # 💡 增加精简的区分符
                    unique_id = str(random.randint(100, 999))
                    item.update({
                        "name": f"{item.get('name', '工蜂')}-{unique_id}",
                        "balance": 100000.0, "total_assets": 100000.0,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "logs": ["诞生于蜂群"], "positions": {}, "fly_count": 0, "memory": "纯净"
                    })
                    supabase.table("drones").insert(item).execute()
                    return item['name']
                except Exception as e: return None

            with ThreadPoolExecutor(max_workers=count) as exe:
                names = list(exe.map(spawn, range(count)))
            
            st.success(f"✅ 成功孵化: {', '.join(filter(None, names))}")
            time.sleep(1.5) # 💡 给数据库写入留出同步时间
            st.rerun()

with tabs[2]:
    if st.button("🔥 一键清空蜂群"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()