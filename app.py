import streamlit as st

# --- 1. 架构红线：全局常量与进化基因库 ---
VERSION = "v9.1 (Behavioral Finance)"
RISK_LEVELS = ["激进", "中立", "保守"]
TIME_FRAMES = ["长线交易", "短线交易", "极短线交易"]
INSTITUTION_MODELS = ["波动率专家", "末日博弈", "机构大单", "黄金猎手"]
MOODS = ["🦁 贪婪", "🐰 恐惧", "⚖️ 冷静"]

st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

import json, time, os, random, pytz
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 2. 虎眼级穿透工具 ---
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
                "合约": o.details.ticker, "行权价": o.details.strike_price, "现价": round(op, 3),
                "Δ Delta": round(get_val(g, 'delta'), 3), "Γ Gamma": round(get_val(g, 'gamma'), 4), "成交量": vol
            })
        return {"ticker": tk, "price": curr_p, "df": pd.DataFrame(rows).sort_values(by="成交量", ascending=False) if rows else pd.DataFrame()}
    except: return {"ticker": ticker, "price": 0.0, "df": pd.DataFrame()}

# --- 3. 演化核心：四维性格研判 ---
def execute_evolution(d, slot, clients):
    with slot:
        # 提取四维基因
        risk = d.get('risk_level', '中立')
        tf = d.get('time_frame', '短线交易')
        style = d.get('style', '黄金猎手')
        mood = d.get('mood', '⚖️ 冷静')

        targets = d.get('portfolio') or ['GLD']
        st.write(f"📡 **{d['name']} ({mood}) 正在研判情报...**")
        
        with ThreadPoolExecutor(max_workers=len(targets)) as exe:
            results = [exe.submit(fetch_tiger_intel, tk, clients['poly']).result() for tk in targets]
        
        ai_brief = {}
        for res in results:
            if res['price'] > 0:
                st.subheader(f"💎 {res['ticker']} 情报 (现价: ${res['price']:.2f})")
                st.dataframe(res['df'].head(5), use_container_width=True)
                ai_brief[res['ticker']] = {"price": res['price'], "options": res['df'].head(5).to_dict('records')}

        # 💡 四维性格化 Prompt
        raw_t = """
        你是工蜂交易员 [N]。
        你的性格 DNA：
        - 情绪状态：[MOOD]
        - 激进程度：[RISK]
        - 交易期限：[TF]
        - 机构模型：[STYLE]
        
        当前现金: [B] | 情报: [I]
        要求：
        1. 必须以你当前的情绪倾向 [MOOD] 出发进行思考。
        2. 如果你是贪婪的，寻找那些可能翻倍的机会；如果你是恐惧的，寻找保护和离场理由。
        3. 返回 JSON: {"thought": "体现性格的中文分析", "trades": []}
        """
        final_prompt = raw_t.replace("[N]", d['name']).replace("[MOOD]", mood).replace("[RISK]", risk)\
                             .replace("[TF]", tf).replace("[STYLE]", style).replace("[B]", str(d['balance']))\
                             .replace("[I]", json.dumps(ai_brief, ensure_ascii=False))
        
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=final_prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            st.success(f"💭 {d['name']} ({mood}) 研判:\n\n{decision.get('thought')}")
            
            clients['supabase'].table("drones").update({
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {mood} | {decision.get('thought')}"] + (d.get('logs') or []))[:10]
            }).eq("id", d["id"]).execute()
        except: st.error("研判中断")

# --- 4. UI 渲染与基因孵化 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

# (此处省略集群放飞按钮逻辑，与 v9.0 一致)

tabs = st.tabs(["🏆 蜂群看板", "👑 基因工程", "⚙️ 系统"])
with tabs[0]:
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | {d.get('mood','-')} | {d.get('risk_level','-')}", expanded=True):
            st.write(f"🧬 **基因链:** {d.get('style')} / {d.get('time_frame')}")
            if st.button(f"🎯 唤醒并演化", key=f"f_{d['id']}"): execute_evolution(d, st.container(), clients)

with tabs[1]:
    st.subheader("👑 孵化定制化基因工蜂")
    name = st.text_input("工蜂名:", f"AI-{random.randint(100,999)}")
    c1, c2 = st.columns(2)
    g_risk = c1.select_slider("激进程度:", options=RISK_LEVELS, value="中立")
    g_mood = c2.selectbox("情绪倾向:", MOODS)
    c3, c4 = st.columns(2)
    g_tf = c3.selectbox("交易期限:", TIME_FRAMES)
    g_style = c4.selectbox("机构模型:", INSTITUTION_MODELS)
    
    if st.button("🔥 立即注入 DNA 并孵化"):
        clients['supabase'].table("drones").insert({
            "name": name, "risk_level": g_risk, "mood": g_mood, "time_frame": g_tf, "style": g_style,
            "balance": 100000.0, "total_assets": 100000.0, "portfolio": ["GLD"], "positions": {}
        }).execute(); st.rerun()