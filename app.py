import streamlit as st

# --- 1. 全局常量 ---
VERSION = "v9.5 (Core Metrics Dashboard)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

import json, time, os, random, pytz
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 2. 核心工具 (保持虎眼穿透逻辑) ---
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_hive_engine():
    try:
        return {
            "supabase": create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]),
            "gen_client": genai.Client(api_key=st.secrets["GEMINI_KEY"]),
            "poly": RESTClient(api_key=st.secrets["POLYGON_KEY"])
        }, None
    except Exception as e: return None, str(e)

def fetch_tiger_intel(ticker, poly):
    try:
        time.sleep(random.uniform(0.1, 0.4))
        tk = ticker.upper()
        sn = poly.get_snapshot_ticker("stocks", tk)
        prev = poly.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        lt, day = getattr(sn, 'last_trade', None), getattr(sn, 'day', None)
        curr_p = get_val(lt, 'p', 'price') or get_val(day, 'c') or y_close
        
        chain = list(poly.list_snapshot_options_chain(tk, params={"strike_price.gte": curr_p*0.9, "strike_price.lte": curr_p*1.1, "limit": 15}))
        rows = []
        for o in chain:
            vol, oi = int(get_val(o.day, 'volume')), int(get_val(o, 'open_interest'))
            g = getattr(o, 'greeks', None)
            olq = getattr(o, 'last_quote', None)
            op = (get_val(olq, 'p', 'bid') + get_val(olq, 'P', 'ask'))/2 or get_val(getattr(o, 'last_trade', None), 'p')
            if op <= 0: continue
            rows.append({
                "信号": "🔥新开仓" if (vol > oi and vol > 100) else "-",
                "合约": o.details.ticker, "现价": round(op, 3),
                "Δ Delta": round(get_val(g, 'delta'), 3), "成交量": vol
            })
        return {"ticker": tk, "price": curr_p, "df": pd.DataFrame(rows) if rows else pd.DataFrame()}
    except: return {"ticker": ticker, "price": 0.0, "df": pd.DataFrame()}

# --- 3. 放飞与结算引擎 ---
def execute_flight(d, slot, clients):
    with slot:
        persona = d.get('style', '稳健交易员')
        targets = d.get('portfolio') or ['GLD']
        st.write(f"🚀 **{d['name']} 正在扫描市场...**")
        
        with ThreadPoolExecutor(max_workers=len(targets)) as exe:
            results = [exe.submit(fetch_tiger_intel, tk, clients['poly']).result() for tk in targets]
        
        ai_brief = {}
        for res in results:
            if res['price'] > 0:
                st.subheader(f"💎 {res['ticker']} 现价: ${res['price']:.2f}")
                st.dataframe(res['df'].head(5), use_container_width=True)
                ai_brief[res['ticker']] = {"price": res['price'], "options": res['df'].to_dict('records')}

        raw_t = """你是工蜂交易员 [N]。灵魂特质: [PERSONA]。现金: [B] | 情报: [I]。
        请进行中文分析，并在最后严格以 JSON 格式输出交易指令。
        返回格式：{"thought": "...", "trades": [{"ticker": "代码", "qty": 数量, "action": "BUY/SELL"}]}"""
        
        final_prompt = raw_t.replace("[N]", d['name']).replace("[PERSONA]", persona)\
                             .replace("[B]", str(d['balance'])).replace("[I]", json.dumps(ai_brief, ensure_ascii=False))
        
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=final_prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            st.success(f"💭 {d['name']} 研判:\n\n{decision.get('thought')}")
            
            # --- 💰 结算核心 ---
            nb, np, logs = float(d.get('balance', 100000)), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker','').upper(), abs(int(t.get('qty',0))), t.get('action','').upper()
                px = 0.0
                if sym in ai_brief: px = ai_brief[sym]['price']
                else:
                    for info in ai_brief.values():
                        for o in info['options']:
                            if o['合约'] == sym: px = o['现价']
                
                if px > 0 and qty > 0:
                    multiplier = 100 if (len(sym) > 6) else 1
                    cost = px * qty * multiplier
                    if act == 'BUY' and nb >= cost:
                        nb -= cost; np[sym] = np.get(sym, 0) + qty; logs.append(f"买入 {qty} {sym}")
                    elif act == 'SELL' and np.get(sym, 0) >= qty:
                        nb += cost; np[sym] -= qty
                        if np[sym] <= 0: del np[sym]
                        logs.append(f"卖出 {qty} {sym}")

            # 持久化
            clients['supabase'].table("drones").update({
                "balance": nb, "positions": np,
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {decision.get('thought')[:50]}..."] + (d.get('logs') or []))[:10]
            }).eq("id", d["id"]).execute()
            
        except Exception as e: st.error(f"放飞异常: {e}")

# --- 4. 界面布局与看板渲染 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

h1, h2 = st.columns([4, 1])
if h2.button("🚀 集群全量放飞", type="primary"):
    for d in d_res:
        with st.status(f"🐝 调度 {d['name']}...", expanded=True):
            execute_flight(d, st.container(), clients)
    st.rerun()

tabs = st.tabs(["🏆 蜂群看板", "👑 基因孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("请先前往“基因孵化”创建工蜂。")
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 巡逻: {d.get('patrol_count',0)}次", expanded=True):
            # 🚨 核心看板区
            cash = d.get('balance', 100000.0)
            # 计算持仓资产市值 (简化处理)
            pos_val = 0.0 # 这里可以后续接入实时行情循环计算
            total_assets = cash + pos_val
            
            m1, m2, m3 = st.columns(3)
            m1.metric("现金 (Cash)", f"${cash:,.2f}")
            m2.metric("持仓市值 (Market Value)", f"${pos_val:,.2f}")
            m3.metric("总资产 (Total Assets)", f"${total_assets:,.2f}", delta=f"{total_assets-100000.0:,.2f}")

            st.divider()
            
            c1, c2 = st.columns([2, 1])
            with c1:
                st.write(f"🧬 **灵魂描述:** {d.get('style')}")
            with c2:
                st.write("**📦 当前持仓:**")
                if d.get('positions'): st.json(d['positions'])
                else: st.caption("暂无持仓")
            
            if st.button(f"🚀 单独放飞 {d['name']}", key=f"f_{d['id']}"):
                execute_flight(d, st.container(), clients)