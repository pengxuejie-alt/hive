import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 初始化 ---
VERSION = "v4.0 (Full Insight)"
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

# --- 2. 价格采集 (高可靠版) ---
def fetch_nectar(ticker):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        price = getattr(sn, 'price', 0) or (getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') else getattr(sn.prev_day, 'c', 0))
        return {"代码": ticker, "现价": price, "涨跌%": round(getattr(sn, 'todays_change_percent', 0), 2)}
    except: return {"代码": ticker, "现价": 0}

# --- 3. 神经调度 ---
def safe_brain_decision(prompt):
    for attempt in range(3):
        try:
            time.sleep(random.uniform(0.1, 0.3))
            r = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=prompt, config={'response_mime_type': 'application/json'})
            data = json.loads(r.text)
            return data[0] if isinstance(data, list) else data
        except Exception as e:
            if "429" in str(e): time.sleep(2); continue
            raise e

# --- 4. 演化核心 (数据写入修正) ---
def execute_worker_cycle(d, slot):
    with slot:
        try:
            st.write("📡 **正在嗅探实时行情...**")
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_nectar, d.get('portfolio', ['GLD'])))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            
            # 显示读取到的行情
            st.info(f"📊 当前行情快照: {nectar_data}")

            st.write(f"🧠 **神经研判中...**")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。记忆:{d.get('memory','无')}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data)}。返回决策JSON。"
            decision = safe_brain_decision(prompt)

            # 结算交易
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

            # 更新数据
            mv = sum(q * fetch_nectar(s)['现价'] * (100 if "O:" in s else 1) for s, q in np.items())
            new_logs = ([f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')} | 🧠 {decision.get('thought','')}"] + (d.get('logs') or []))[:20]
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": new_logs,
                "memory": decision.get('learning', d.get('memory')),
                "fly_count": (d.get('fly_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            st.success("✅ 演化已写入日志")
        except Exception as e:
            st.error(f"❌ 运行失败: {e}")

# --- 5. UI 布局 ---
st.set_page_config(page_title="Hive 蜂群面板", layout="wide")

h1, h2 = st.columns([4, 1])
h1.title(f"🐝 Hive 蜂群生态系统 `{VERSION}`")
full_fly = h2.button("🔥 全量放飞", type="primary", use_container_width=True)

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data
if full_fly and d_res:
    for d in d_res: st.session_state[f"run_{d['id']}"] = True

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("请先孵化。")
    for d in d_res:
        is_active = st.session_state.get(f"run_{d['id']}", False)
        # 档案标题栏
        label = f"🐝 {d['name']} | 资产: ${d['total_assets']:,.2f} | 现金: ${d['balance']:,.2f}"
        with st.expander(label, expanded=is_active):
            col_info, col_data = st.columns([2, 3])
            with col_info:
                st.markdown(f"**🧬 基因属性:**\n> {d.get('persona', '待定义')}")
                st.markdown(f"**🧠 长期记忆:**\n> {d.get('memory', '尚无记忆')}")
                st.write(f"📈 **累计放飞:** {d.get('fly_count', 0)} 次")
            with col_data:
                st.write("**📦 当前持仓:**")
                st.json(d.get('positions', {}))
            
            slot = st.container()
            if st.button(f"🚀 单独放飞", key=f"btn_{d['id']}") or is_active:
                execute_worker_cycle(d, slot)
                if is_active: st.session_state[f"run_{d['id']}"] = False
                st.rerun()
            
            st.write("**📜 演化日志:**")
            for l in (d.get('logs') or [])[:10]: st.caption(l)

with tabs[1]:
    st.subheader("👑 蜂后批量孵化")
    c1, c2 = st.columns([3, 1])
    instr = c1.text_area("孵化指令:", value="孵化3只德州之神项目的工蜂，要有赌场高手的霸气")
    count = c2.number_input("数量", 1, 10, 3)
    if st.button("🔥 开始孵化"):
        with st.spinner("正在合成基因..."):
            def spawn(idx):
                p = f"设计JSON：{{'name':'3字中文名','logic':'逻辑','persona':'性格','portfolio':['GLD']}}。内容中文。指令：{instr}。扰动：{time.time()}"
                item = safe_brain_decision(p)
                item.update({"balance": 100000.0, "total_assets": 100000.0, "created_at": datetime.now(timezone.utc).isoformat(), "logs": ["诞生"], "positions": {}, "fly_count": 0, "memory": "初始状态"})
                supabase.table("drones").insert(item).execute()
                return item['name']
            with ThreadPoolExecutor(max_workers=count) as exe:
                names = list(exe.map(spawn, range(count)))
            st.success(f"✅ 成功: {', '.join(filter(None, names))}")
            st.rerun()

with tabs[2]:
    if st.button("🔥 清空所有数据"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()