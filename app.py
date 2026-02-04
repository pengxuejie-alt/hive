import streamlit as st
import re
import json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai
from polygon import RESTClient

# --- 1. 强制 UI 占位 (防止标题都不显示) ---
st.set_page_config(page_title="Hive 蜂群系统", layout="wide")
st.title("🐝 Hive 蜂群生态系统") # 先把标题打在屏幕上

# --- 2. 安全初始化逻辑 ---
def get_config(key): 
    return os.environ.get(key) or st.secrets.get(key)

@st.cache_resource
def init_clients():
    try:
        s_url = get_config("SUPABASE_URL")
        s_key = get_config("SUPABASE_KEY")
        g_key = get_config("GEMINI_KEY")
        p_key = get_config("POLYGON_KEY")
        
        if not all([s_url, s_key, g_key, p_key]):
            return None, "⚠️ 环境变量(Secrets)配置不全，请检查 Streamlit 设置。"
            
        return {
            "supabase": create_client(s_url, s_key),
            "gen_client": genai.Client(api_key=g_key),
            "poly_client": RESTClient(api_key=p_key)
        }, None
    except Exception as e:
        return None, f"❌ 客户端连接失败: {str(e)}"

clients, err_msg = init_clients()

if err_msg:
    st.error(err_msg)
    st.info("💡 提示：如果标题能显示但下面报错，说明是 API Key 或数据库 URL 的问题。")
    st.stop()

supabase = clients["supabase"]
gen_client = clients["gen_client"]
poly_client = clients["poly_client"]

# --- 3. 核心工具函数 ---
def safe_brain_decision(prompt):
    try:
        r = gen_client.models.generate_content(
            model="gemini-2.0-flash", 
            contents=prompt, 
            config={'response_mime_type': 'application/json'}
        )
        data = json.loads(r.text)
        return data[0] if isinstance(data, list) else data
    except: return None

def fetch_nectar(ticker):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        price = getattr(sn, 'price', 0) or (getattr(sn.last_trade, 'p', 0) if hasattr(sn, 'last_trade') else getattr(sn.prev_day, 'c', 0))
        return {"代码": ticker, "现价": price}
    except: return {"代码": ticker, "现价": 0}

# --- 4. 演化逻辑 (字段严格对齐清单) ---
def execute_worker_cycle(d, slot):
    with slot:
        try:
            st.write("📡 **正在穿透行情...**")
            targets = d.get('portfolio', ['GLD'])
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_nectar, targets))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            
            st.info(f"📊 实时行情: {json.dumps(nectar_data, ensure_ascii=False)}")
            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。现金:{d['balance']}。行情:{json.dumps(nectar_data)}。返回决策JSON。"
            decision = safe_brain_decision(prompt)

            # 资产结算
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
            
            # 💡 精准匹配你提供的 JSON 字段名
            supabase.table("drones").update({
                "balance": nb,
                "positions": np,
                "total_assets": total,
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')}"] + (d.get('logs') or []))[:10],
                "memory": decision.get('learning', d.get('memory')),
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "peak_balance": max(d.get('peak_balance', 0) or 0, total),
                "fitness_score": round((total / (d.get('initial_balance', 100000.0) or 100000.0)) * 100, 2)
            }).eq("id", d["id"]).execute()
            
            st.success("✅ 演化记录已入库")
            time.sleep(1); st.rerun()
        except Exception as e:
            st.error(f"❌ 演化失败: {e}")

# --- 5. 档案面板 ---
d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res:
        st.info("⚠️ 档案库为空。请先前往‘蜂后孵化’。")
    else:
        for d in d_res:
            label = f"🐝 {d.get('name')} | 资产: ${d.get('total_assets',0):,.2f} | 适应度: {d.get('fitness_score',0)}"
            with st.expander(label):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"🧬 **基因:** {d.get('persona')}")
                    st.write(f"🧠 **记忆:** {d.get('memory')}")
                    st.caption(f"巡逻次数: {d.get('patrol_count', 0)}")
                with c2:
                    st.write("**📦 持仓:**")
                    st.json(d.get('positions', {}))
                
                if st.button(f"🚀 单独演化", key=f"f_{d['id']}"):
                    execute_worker_cycle(d, st.container())

with tabs[1]:
    st.subheader("👑 蜂后集群孵化")
    instr = st.text_area("孵化指令:", value="孵化3只德州之神工蜂")
    if st.button("🔥 执行孵化"):
        # 简单提取数量逻辑
        count = 1
        match = re.search(r'(\d+)只', instr)
        if match: count = int(match.group(1))
        
        with st.spinner(f"🧬 正在并行合成 {count} 只工蜂..."):
            def spawn(idx):
                p = f"设计JSON：{{'name':'','logic':'','persona':'','style':'','focus':'','portfolio':['GLD']}}。指令：{instr}。"
                item = safe_brain_decision(p)
                if item:
                    uid = f"{random.randint(100,999)}"
                    new_drone = {
                        "name": f"{item.get('name', '工蜂')}-{uid}",
                        "persona": item.get('persona', '初始'),
                        "logic": item.get('logic', '德州策略'),
                        "balance": 100000.0,
                        "initial_balance": 100000.0,
                        "total_assets": 100000.0,
                        "patrol_count": 0,
                        "positions": {},
                        "logs": ["诞生"],
                        "created_at": datetime.now(timezone.utc).isoformat()
                    }
                    supabase.table("drones").insert(new_drone).execute()
                    return new_drone['name']
            
            with ThreadPoolExecutor(max_workers=count) as exe:
                exe.map(spawn, range(count))
            st.success("✅ 批量孵化任务已发送，请刷新页面。")
            time.sleep(2); st.rerun()

with tabs[2]:
    if st.button("🔥 清空数据"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()