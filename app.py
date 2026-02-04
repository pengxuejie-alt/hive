import streamlit as st
import re, json, time, os, random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai
from polygon import RESTClient

# --- 1. 核心初始化 ---
st.set_page_config(page_title="Hive 金融蜂群", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

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

# --- 2. 演化核心逻辑 (纯净版) ---
def execute_worker_cycle(d, slot):
    with slot:
        try:
            # 1. 获取情报
            st.write("🔍 **情报搜集：正在读取实时股价...**")
            targets = d.get('portfolio', ['GLD'])
            def fetch_px(t):
                try:
                    sn = poly_client.get_snapshot_ticker("stocks", t)
                    px = getattr(sn, 'price', 0) or getattr(sn.last_trade, 'p', 0)
                    return {"代码": t, "现价": px}
                except: return {"代码": t, "现价": 0}
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_px, targets))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            st.info(f"📈 实时行情汇总：{json.dumps(nectar_data, ensure_ascii=False)}")

            # 2. 神经决策 (强制中文 + 金融逻辑)
            st.write("🧠 **研判分析：中枢神经逻辑运算...**")
            prompt = f"""
            你是金融交易工蜂 {d['name']}。
            基因性格: {d['persona']}
            资产状况: 现金 {d['balance']} | 持仓 {json.dumps(d.get('positions'))}
            市场情报: {json.dumps(nectar_data)}
            
            请用【中文】返回以下JSON格式，严禁包含任何赌博或德州扑克术语：
            {{
                "thought": "对当前市场行情和资产配比的专业中文分析",
                "trades": [{"ticker": "代码", "qty": 数量, "action": "BUY/SELL"}],
                "learning": "本次交易对未来策略的中文修正建议"
            }}
            """
            r = gen_client.models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]
            st.success(f"💭 思考逻辑：{decision.get('thought')}")

            # 3. 交易执行
            st.write("⚖️ **执行阶段：提交交易指令...**")
            nb, np, reports = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty = t.get('ticker', '').upper(), t.get('qty', 0)
                px = nectar_data.get(sym, {}).get('现价', 0)
                if px <= 0: continue
                # 简易期权乘数
                multiplier = 100 if len(sym) > 6 else 1
                cost = qty * px * multiplier
                
                if t.get('action') == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"买入 {sym} {qty}股")
                elif t.get('action') == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"卖出 {sym} {qty}股")

            action_summary = " | ".join(reports) if reports else "维持观望"
            # 存入数据库的日志细节
            log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] 动作:{action_summary} | 思考:{decision.get('thought')}"
            
            mv = sum(q * nectar_data.get(s, {}).get('现价', 0) for s, q in np.items())
            total = round(nb + mv, 2)

            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": total,
                "logs": ([log_msg] + (d.get('logs') or []))[:10],
                "memory": decision.get('learning', d.get('memory')),
                "patrol_count": (d.get('patrol_count', 0) + 1)
            }).eq("id", d["id"]).execute()
            
            st.write(f"📝 **演化结果：{action_summary}**")
        except Exception as e: st.error(f"放飞中断: {str(e)}")

# --- 3. 界面显示 ---
h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 纯净金融演化模式")
full_fly = h2.button("🔥 一键全量放飞", type="primary", use_container_width=True)

d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data

if full_fly:
    for d in d_res:
        with st.status(f"🐝 正在执行 {d['name']} 的放飞任务...", expanded=True) as status:
            execute_worker_cycle(d, status)
    st.success("✅ 集群放飞任务已按序完成")
    st.button("🔄 立即刷新数据")
    st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("当前蜂巢为空。")
    for d in d_res:
        with st.expander(f"🐝 {d.get('name')} | 资产: ${d.get('total_assets',0):,.2f} | 累计放飞: {d.get('patrol_count',0)}次"):
            c_l, c_r = st.columns(2)
            with c_l:
                st.write(f"🧬 **基因:** {d.get('persona')}")
                st.write(f"🧠 **记忆/教训:** {d.get('memory')}")
            with c_r:
                st.write("**📦 当前持仓:**"); st.json(d.get('positions', {}))
            if st.button(f"🚀 单独放飞", key=f"btn_{d['id']}"):
                with st.status("单体演化中...") as s: execute_worker_cycle(d, s)
                st.rerun()
            for l in (d.get('logs') or [])[:3]: st.caption(l)

with tabs[1]:
    st.subheader("👑 蜂后孵化")
    instr = st.text_area("输入孵化指令 (例如：孵化3只GLD量化交易员):", value="孵化3只GLD量化交易员")
    if st.button("🔥 开始孵化"):
        # ... (识别指令中的数量并执行 insert) ...
        st.success("指令已发出，请稍后刷新。"); time.sleep(1.5); st.rerun()

with tabs[2]:
    st.subheader("⚙️ 系统管理")
    if st.button("🗑️ 彻底清空蜂巢数据", type="secondary"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute()
        st.success("数据库已重置"); time.sleep(1); st.rerun()