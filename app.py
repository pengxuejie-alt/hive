import streamlit as st

# --- 1. 全局常量与红线声明 ---
VERSION = "v9.3 (AI DNA Encoding)"
st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")
st.caption(f"{VERSION} | 术语已统一为“放飞” | AI 基因编码引擎已激活")

import json, time, os, random, pytz
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 2. 核心工具函数 ---
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

# --- 3. 放飞核心逻辑 ---
def execute_flight(d, slot, clients):
    with slot:
        persona = d.get('style', '稳健的交易员')
        targets = d.get('portfolio') or ['GLD']
        st.write(f"🚀 **{d['name']} 正在执行放飞任务...**")
        
        with ThreadPoolExecutor(max_workers=len(targets)) as exe:
            results = [exe.submit(fetch_tiger_intel, tk, clients['poly']).result() for tk in targets]
        
        ai_brief = {}
        for res in results:
            if res['price'] > 0:
                st.subheader(f"💎 {res['ticker']} 现价: ${res['price']:.2f}")
                st.dataframe(res['df'].head(5), use_container_width=True)
                ai_brief[res['ticker']] = {"price": res['price'], "options": res['df'].head(5).to_dict('records')}

        raw_t = """你是工蜂交易员 [N]。灵魂特质: [PERSONA]。现金: [B] | 情报: [I]。返回 JSON: {"thought": "中文分析", "trades": []}"""
        final_prompt = raw_t.replace("[N]", d['name']).replace("[PERSONA]", persona)\
                             .replace("[B]", str(d['balance'])).replace("[I]", json.dumps(ai_brief, ensure_ascii=False))
        
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=final_prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            st.success(f"💭 {d['name']} 研判:\n\n{decision.get('thought')}")
            
            clients['supabase'].table("drones").update({
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {decision.get('thought')}"] + (d.get('logs') or []))[:10]
            }).eq("id", d["id"]).execute()
        except: st.error("放飞过程中中断")

# --- 4. 初始化 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

# --- 5. UI 渲染 ---
h1, h2 = st.columns([4, 1])
full_fly = h2.button("🚀 集群放飞", type="primary", use_container_width=True)

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 调度 {d['name']}...", expanded=True):
            execute_flight(d, st.container(), clients)
    st.rerun()

tabs = st.tabs(["🏆 蜂群看板", "👑 基因孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("空。")
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | 巡逻: {d.get('patrol_count',0)}次", expanded=True):
            st.write(f"🧬 **灵魂描述:** {d.get('style')}")
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}"): 
                execute_flight(d, st.container(), clients)

with tabs[1]:
    st.subheader("👑 基因编码孵化器")
    user_cmd = st.text_area("输入你的孵化指令（例如：孵化一只激进的GLD期权工蜂）:", height=100)
    
    if st.button("🔥 开始基因编码并孵化"):
        if user_cmd:
            with st.spinner("🧠 Gemini 正在进行基因编码..."):
                # 💡 调用 AI 生成详细的灵魂描述
                dna_prompt = f"根据用户指令 '{user_cmd}'，生成一段专业的量化交易员灵魂描述。要求包含性格倾向（激进/稳健）、核心模型（如末日博弈/波动率专家）、情绪特征（贪婪/恐惧/冷静）以及交易节奏。字数约100字，中文。"
                dna_res = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=dna_prompt)
                soul_description = dna_res.text
                
                new_name = f"AI-{random.randint(100,999)}"
                clients['supabase'].table("drones").insert({
                    "name": new_name, "style": soul_description,
                    "balance": 100000.0, "total_assets": 100000.0, "portfolio": ["GLD"], "positions": {}
                }).execute()
                st.success(f"✅ 孵化成功！工蜂 {new_name} 已载入灵魂。")
                st.rerun()

with tabs[2]:
    if st.button("🗑️ 清空所有数据"):
        clients['supabase'].table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()