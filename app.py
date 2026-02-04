import streamlit as st
import json, time, os, random, re, pytz
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 初始化与配置
# ==========================================
VERSION = "v11.9 (Audit Complete)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")

@st.cache_resource
def init_hive_engine():
    try:
        return {
            "supabase": create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]),
            "gen_client": genai.Client(api_key=st.secrets["GEMINI_KEY"]),
            "poly": RESTClient(api_key=st.secrets["POLYGON_KEY"])
        }, None
    except Exception as e: return None, str(e)

cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

# ==========================================
# 2. 虎眼级行情与解析工具
# ==========================================
def parse_option_symbol(symbol):
    if not symbol.startswith("O:"): return symbol
    match = re.match(r"O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d+)", symbol)
    if match:
        tk, yy, mm, dd, cp, strike = match.groups()
        strike_val = int(strike) / 1000
        return f"{tk} {mm}/{dd} ${strike_val} {'Call' if cp == 'C' else 'Put'}"
    return symbol

def get_verified_price(poly, symbol):
    ticker = symbol if symbol.startswith("O:") else f"O:{symbol}"
    try:
        # 1. 优先分钟线聚合 (过滤 Volume=0)
        end = datetime.now()
        start = end - timedelta(days=5)
        aggs = poly.get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        if aggs:
            for i in range(len(aggs)-1, -1, -1):
                if aggs[i].volume > 0: return float(aggs[i].close)
        
        # 2. 兜底取昨日收盘
        prev = poly.get_previous_close_agg(ticker)
        if prev: return float(prev[0].close)
        return 0.0
    except: return 0.0

def calculate_age(created_at_str):
    try:
        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
        delta = datetime.now(pytz.UTC) - created_at
        if delta.days > 0: return f"{delta.days}天 {delta.seconds // 3600}小时"
        return f"{delta.seconds // 3600}小时"
    except: return "刚刚诞生"

# ==========================================
# 3. 🚨 核心：三维度审计放飞引擎
# ==========================================
def execute_flight_v11(d, slot, clients):
    with slot:
        dna = d.get('style', 'Risk:Neutral')
        history = (d.get('logs') or [])[:3]
        tk = "GLD"
        curr_p = get_verified_price(clients['poly'], tk)
        
        st.write(f"🚀 **{d['name']} 正在进行三维度深度研判...**")
        
        prompt = f"""你是交易工蜂 {d['name']}。
        🧬 DNA特征: {dna} | 🧠 记忆: {history}
        当前数据: 现金 ${d['balance']:,.2f}, 持仓 {json.dumps(d.get('positions'))}, {tk}现价 ${curr_p}
        
        请严格按 JSON 返回：
        {{
          "data_summary": "记录关键价格和波动",
          "thought": "你的逻辑思考",
          "action_logic": "动作说明",
          "trades": [{{"ticker": "代码", "qty": 50, "action": "BUY/SELL"}}]
        }}
        """
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            res = json.loads(r.text)
            
            # 结算
            nb, np = float(d['balance']), (d.get('positions') or {}).copy()
            execution = []
            for t in res.get('trades', []):
                sym, qty, act = t['ticker'].upper(), int(t['qty']), t['action'].upper()
                px = get_verified_price(clients['poly'], sym)
                if px <= 0: continue
                cost = px * qty * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    execution.append(f"买入 {qty} {sym} @${px}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    execution.append(f"卖出 {qty} {sym} @${px}")

            # 构造三段式日志
            act_msg = " | ".join(execution) if execution else "持仓观望"
            full_log = f"📊 数据: {res.get('data_summary')} | 🧠 思考: {res.get('thought')[:80]}... | ⚡ 行动: {act_msg}"
            
            clients['supabase'].table("drones").update({
                "balance": nb, "positions": np,
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "logs": ([full_log] + (d.get('logs') or []))[:15]
            }).eq("id", d["id"]).execute()
            
            st.success(f"✅ {d['name']} 执行完毕")
            return True
        except Exception as e:
            st.error(f"失败: {e}"); return False

# ==========================================
# 4. UI 渲染 (完整 Tab 逻辑)
# ==========================================
st.title("🐝 Hive 智能金融蜂群")
tabs = st.tabs(["🏆 蜂群看板", "👑 DNA 孵化器", "⚙️ 管理"])

with tabs[0]:
    d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 存活: {calculate_age(d.get('created_at'))}", expanded=True):
            cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
            mv_total, pos_table = 0.0, []
            if pos:
                with st.spinner("同步持仓市值..."):
                    for sym, qty in pos.items():
                        px = get_verified_price(clients['poly'], sym)
                        mv = px * qty * (100 if "O:" in sym else 1)
                        mv_total += mv
                        pos_table.append({"合约": parse_option_symbol(sym), "数量": f"{qty}手", "单价": f"${px:.4f}", "市值": f"${mv:,.2f}"})

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("现金", f"${cash:,.2f}")
            m2.metric("持仓市值", f"${mv_total:,.2f}")
            m3.metric("总资产", f"${cash+mv_total:,.2f}", delta=f"{((cash+mv_total)/100000-1)*100:.2f}%")
            m4.metric("巡逻", d.get('patrol_count', 0))

            st.divider()
            c_dna, c_act = st.columns([4, 1])
            dna_raw = d.get('style', '')
            with c_dna:
                st.write("🧬 **DNA 序列**")
                if " | " in dna_raw:
                    cols = st.columns(len(dna_raw.split(' | ')))
                    for i, f in enumerate(dna_raw.split(' | ')): cols[i].code(f)
                else: st.info(dna_raw)
            with c_act:
                if st.button("🧬 基因重组", key=f"re_{d['id']}", type="primary"):
                    new_dna = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=f"重构为特征短语: {dna_raw}").text.strip()
                    clients['supabase'].table("drones").update({"style": new_dna}).eq("id", d["id"]).execute()
                    st.rerun()

            st.divider()
            c1, c2 = st.columns([1, 1.5])
            with c1:
                st.write("🧠 **三维度审计记忆 (Data/Thought/Action)**")
                with st.container(height=250):
                    for l in (d.get('logs') or []): st.caption(l)
                if st.button(f"🚀 放飞 {d['name']}", key=f"f_{d['id']}", type="primary", use_container_width=True):
                    if execute_flight_v11(d, st.container(), clients): st.rerun()
            with c2:
                st.write("**📦 实盘持仓**")
                if pos_table: st.table(pos_table)
                else: st.caption("空仓")

with tabs[1]:
    st.subheader("👑 DNA 孵化器")
    u_cmd = st.text_input("描述新蜜蜂性格:")
    if st.button("🔥 孵化"):
        dna = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=f"将'{u_cmd}'转化为'特征:值 | 特征:值'短语").text.strip()
        clients['supabase'].table("drones").insert({"name": f"AI-{random.randint(100,999)}", "style": dna, "balance": 100000.0, "positions": {}}).execute()
        st.rerun()

with tabs[2]:
    if st.button("🗑️ 清空所有工蜂"):
        clients['supabase'].table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()