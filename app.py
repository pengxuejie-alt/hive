import streamlit as st
import re, json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai
from polygon import RESTClient

# --- 1. 核心初始化 ---
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
supabase, gen_client, poly_client = clients["supabase"], clients["gen_client"], clients["poly_client"]

# --- 2. 演化核心逻辑 (修正死循环与中文强制) ---
def execute_worker_cycle(d, slot):
    with slot:
        try:
            # 1. 获取行情
            st.write("🔍 **第一步：获取行情情报...**")
            targets = d.get('portfolio', ['GLD'])
            def fetch_px(t):
                try:
                    sn = poly_client.get_snapshot_ticker("stocks", t)
                    return {"代码": t, "现价": getattr(sn, 'price', 0) or getattr(sn.last_trade, 'p', 0)}
                except: return {"代码": t, "现价": 0}
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_px, targets))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            st.info(f"📈 行情情报：{json.dumps(nectar_data, ensure_ascii=False)}")

            # 2. 神经决策 (强制中文)
            st.write("🧠 **第二步：中枢神经研判...**")
            prompt = f"""
            你是工蜂 {d['name']}。
            基因性格: {d['persona']}
            当前现金: {d['balance']}
            当前持仓: {json.dumps(d.get('positions'))}
            实时行情: {json.dumps(nectar_data)}
            
            请严格按以下JSON格式返回，所有文字说明必须使用【中文】：
            {{
                "thought": "用中文写下你对当前行情的深度分析",
                "trades": [{"ticker": "代码", "qty": 数量, "action": "BUY/SELL"}],
                "learning": "用中文写下本次放飞的经验教训"
            }}
            """
            r = gen_client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]
            
            st.success(f"💭 思考过程：{decision.get('thought')}")

            # 3. 交易结算
            st.write("⚖️ **第三步：执行交易指令...**")
            nb, np, reports = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty = t.get('ticker', '').upper(), t.get('qty', 0)
                px = nectar_data.get(sym, {}).get('现价', 0)
                if px <= 0: continue
                cost = qty * px * (100 if len(sym) > 5 else 1) # 简易期权判断
                
                if t.get('action') == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"买入 {sym} {qty}股")
                elif t.get('action') == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"卖出 {sym} {qty}股")

            # 写入日志 (存入所有细节)
            trade_str = " | ".join(reports) if reports else "观望"
            log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] 情报:{list(nectar_data.keys())} | 思考:{decision.get('thought')} | 动作:{trade_str}"
            
            # 提交数据库
            mv = sum(q * nectar_data.get(s, {}).get('现价', 0) for s, q in np.items())
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([log_msg] + (d.get('logs') or []))[:10],
                "memory": decision.get('learning', d.get('memory')),
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            
            st.write(f"📝 **结果：{trade_str}**")
        except Exception as e:
            st.error(f"演化中断: {str(e)}")

# --- 3. 界面渲染 ---
h1, h2 = st.columns([4, 1])
full_fly = h2.button("🔥 一键放飞", type="primary", use_container_width=True)

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

# 💡 并行但只飞一次的控制逻辑
if full_fly:
    st.info("🚀 集群放飞中，请勿重复点击...")
    for d in d_res:
        with st.status(f"🐝 正在调度 {d['name']}...", expanded=True) as status:
            execute_worker_cycle(d, status)
    st.success("✅ 集群放飞任务全部完成")
    st.button("🔄 刷新查看最终状态") # 提供手动刷新，防止死循环
    st.stop()

# 档案显示
tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    for d in d_res:
        label = f"🐝 {d.get('name')} | 资产: ${d.get('total_assets',0):,.2f} | 放飞: {d.get('patrol_count',0)}次"
        with st.expander(label):
            col_l, col_r = st.columns(2)
            with col_l:
                st.write(f"🧬 **基因:** {d.get('persona')}")
                st.write(f"🧠 **记忆:** {d.get('memory')}")
            with col_r:
                st.write("**📦 持仓:**")
                st.json(d.get('positions', {}))
            
            # 单独放飞按钮
            if st.button(f"🚀 单独放飞", key=f"one_{d['id']}"):
                with st.status("正在演化...") as s:
                    execute_worker_cycle(d, s)
                st.button("完成并刷新", key=f"ref_{d['id']}")

            st.write("**📜 详细日志 (情报|思考|记录):**")
            for l in (d.get('logs') or [])[:5]: st.caption(l)

# --- 4. 极简孵化逻辑 (略) ---