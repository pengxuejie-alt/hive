import streamlit as st
import json, time, os, random, re, pytz
import pandas as pd  # 🚨 确保 Pandas 在顶部
from datetime import datetime, timedelta
from supabase import create_client
from google import genai 
from polygon import RESTClient

# ==========================================
# 1. 核心初始化 (复刻虎之眼底层架构)
# ==========================================
VERSION = "v13.1 (Syntax & Logic Fix)"
st.set_page_config(page_title="Hive 智能金融审计", layout="wide")

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

def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

# ==========================================
# 2. 虎之眼取价逻辑 (修复 GLD 价格 0 问题)
# ==========================================
def get_verified_price(poly, ticker):
    try:
        is_option = ticker.startswith("O:") or len(ticker) > 10
        if not is_option:
            snap = poly.get_snapshot_ticker("stocks", ticker)
            prev = poly.get_previous_close_agg(ticker)
            y_close = get_val(prev[0] if prev else None, 'close')
            lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
            tp = get_val(lt, 'p', 'price')
            bp, ap = get_val(lq, 'p', 'bid'), get_val(lq, 'P', 'ask')
            return tp if tp > 0 else (((bp + ap) / 2) if (bp > 0 and ap > 0) else y_close)
        else:
            end = datetime.now()
            start = end - timedelta(days=5)
            aggs = poly.get_aggs(ticker, 1, "minute", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if aggs:
                for i in range(len(aggs)-1, -1, -1):
                    if aggs[i].volume > 0: return float(aggs[i].close)
            prev = poly.get_previous_close_agg(ticker)
            return float(prev[0].close) if prev else 0.0
    except: return 0.0

# ==========================================
# 3. 三维度审计引擎 (🚨 修复 ValueError 语法)
# ==========================================
def execute_flight(d, clients):
    dna = d.get('style', 'Risk:Neutral')
    history = (d.get('logs') or [])[:3]
    tk = "GLD"
    curr_p = get_verified_price(clients['poly'], tk)
    
    # 💡 关键修复：所有 JSON 的括号都必须双写 {{ }}
    prompt = f"""你是{d['name']}。DNA:{dna} | 历史:{history}
    数据: 现金${d['balance']}, 持仓{json.dumps(d.get('positions'))}, {tk}现价${curr_p}
    
    要求: 严格按以下 JSON 返回汇报，不要包含任何 Markdown 格式：
    {{
      "data_rpt": "记录当前行情数据点",
      "thought": "基于DNA和记忆的推演",
      "action_plan": "具体操作逻辑",
      "trades": [{{"ticker": "O:代码", "qty": 10, "action": "BUY/SELL"}}]
    }}"""
    
    try:
        r = clients['gen_client'].models.generate_content(
            model="gemini-2.0-flash", 
            contents=prompt, 
            config={'response_mime_type': 'application/json'}
        )
        res = json.loads(r.text)
        nb, np = float(d['balance']), (d.get('positions') or {}).copy()
        exec_logs = []
        for t in res.get('trades', []):
            sym, qty, act = t['ticker'].upper(), int(t['qty']), t['action'].upper()
            px = get_verified_price(clients['poly'], sym)
            if px <= 0: continue
            cost = px * qty * (100 if "O:" in sym else 1)
            if act == 'BUY' and nb >= cost:
                nb -= cost; np[sym] = np.get(sym, 0) + qty
                exec_logs.append(f"买入 {qty}手 {sym} @${px:.2f}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                exec_logs.append(f"卖出 {qty}手 {sym} @${px:.2f}")

        log_entry = f"📊 数据:{res.get('data_rpt')} | 🧠 思考:{res.get('thought')} | ⚡ 行动:{' | '.join(exec_logs) if exec_logs else '观望'}"
        clients['supabase'].table("drones").update({
            "balance": nb, "positions": np, "patrol_count": d.get('patrol_count', 0)+1,
            "logs": ([log_entry] + (d.get('logs') or []))[:20]
        }).eq("id", d["id"]).execute()
        return True
    except Exception as e:
        st.error(f"决策引擎异常: {e}")
        return False

# ==========================================
# 4. 界面渲染 (通栏专业卡片)
# ==========================================
st.title("🐝 Hive 智能金融审计中心")

d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
for d in d_res:
    with st.container(border=True):
        col_name, col_btn = st.columns([5, 1])
        col_name.subheader(f"🐝 {d['name']} (巡逻: {d.get('patrol_count', 0)})")
        if col_btn.button(f"🚀 放飞研判", key=f"f_{d['id']}", type="primary", use_container_width=True):
            if execute_flight(d, clients): st.rerun()

        # 资产指标
        cash, pos = float(d.get('balance', 0.0)), d.get('positions', {})
        mv_total, pos_table = 0.0, []
        for sym, qty in pos.items():
            px = get_verified_price(clients['poly'], sym)
            mv = px * qty * (100 if "O:" in sym else 1)
            mv_total += mv
            pos_table.append({"合约": sym, "持仓": f"{qty}手", "现价": f"${px:.2f}", "估值": f"${mv:,.2f}"})

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("现金", f"${cash:,.2f}")
        m2.metric("持仓市值", f"${mv_total:,.2f}")
        m3.metric("总资产", f"${cash+mv_total:,.2f}")
        m4.metric("审计条数", f"{len(d.get('logs') or [])}")

        st.divider()
        c_l, c_r = st.columns([1, 2])
        with c_l:
            st.write("🧬 **DNA 序列**")
            for f in d.get('style', '').split(' | '): st.code(f)
        with c_r:
            st.write("📦 **实时投资组合**")
            if pos_table: st.dataframe(pd.DataFrame(pos_table), hide_index=True, use_container_width=True)
            else: st.caption("空仓")

        st.divider()
        st.write("🧠 **三维度审计轨迹 (最近 5 条)**")
        for log in (d.get('logs') or [])[:5]:
            with st.chat_message("assistant", avatar="🐝"):
                st.markdown(log)