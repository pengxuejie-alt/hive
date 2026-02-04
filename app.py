import streamlit as st

# --- 1. 全局配置与预设基因模板 ---
VERSION = "v9.2 (Soul Compression)"
PRESET_PERSONAS = {
    "默认黄金猎手": "稳健的黄金专家，中立情绪，关注 GLD 现货与期权联动，追求风险对冲。",
    "激进末日使者": "极其激进的末日博弈者，贪婪情绪，只盯着高 Gamma 合约，追求极短线翻倍爆炸机会。",
    "稳健波动率专家": "保守的波动率专家，冷静情绪，专注于 IV 回归，长线交易，极其厌恶回撤。"
}

st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

import json, time, os, random, pytz
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai 
from polygon import RESTClient

# --- 2. 核心穿透工具 (保持虎眼逻辑) ---
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

# --- 3. 演化核心：语义化决策 ---
def execute_evolution(d, slot, clients):
    with slot:
        # 💡 这里直接读取 style 字段作为“灵魂描述”
        persona = d.get('style', '稳健的交易员')
        targets = d.get('portfolio') or ['GLD']
        st.write(f"📡 **{d['name']} 正在研判情报...**")
        st.caption(f"🧬 当前灵魂特质: {persona}")
        
        with ThreadPoolExecutor(max_workers=len(targets)) as exe:
            results = [exe.submit(fetch_tiger_intel, tk, clients['poly']).result() for tk in targets]
        
        ai_brief = {}
        for res in results:
            if res['price'] > 0:
                st.subheader(f"💎 {res['ticker']} 情报 (现价: ${res['price']:.2f})")
                st.dataframe(res['df'].head(5), use_container_width=True)
                ai_brief[res['ticker']] = {"price": res['price'], "options": res['df'].head(5).to_dict('records')}

        # 💡 语义压缩 Prompt
        raw_t = """
        你是工蜂交易员 [N]。
        你的交易灵魂描述：[PERSONA]
        
        当前现金: [B] | 情报: [I]
        要求：
        1. 必须完全代入你的描述角色进行中文思考。
        2. 如果描述说你是“贪婪”的，你的研判必须体现这种对机会的饥渴。
        3. 返回 JSON: {"thought": "体现灵魂特质的中文分析", "trades": []}
        """
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
        except: st.error("研判中断")

# --- 4. UI 渲染 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

# (主放飞按钮逻辑略)

tabs = st.tabs(["🏆 蜂群看板", "👑 灵魂孵化", "⚙️ 系统"])
with tabs[0]:
    for d in d_res:
        with st.expander(f"🐝 {d['name']} | {d.get('style','-')[:20]}...", expanded=True):
            st.write(f"🧬 **灵魂描述:** {d.get('style')}")
            if st.button(f"🎯 唤醒并演化", key=f"f_{d['id']}"): execute_evolution(d, st.container(), clients)

with tabs[1]:
    st.subheader("👑 灵魂工程：自然语言孵化工蜂")
    name = st.text_input("工蜂代号:", f"AI-{random.randint(100,999)}")
    
    # 💡 增加预设模板选择
    preset = st.selectbox("选择灵魂模板 (或在下方自定义):", ["自定义"] + list(PRESET_PERSONAS.keys()))
    default_text = PRESET_PERSONAS.get(preset, "") if preset != "自定义" else ""
    
    persona_text = st.text_area("在此输入工蜂的灵魂描述（包含激进程度、情绪、模型偏好等）:", value=default_text)
    
    if st.button("🔥 注入灵魂并孵化"):
        clients['supabase'].table("drones").insert({
            "name": name, "style": persona_text,
            "balance": 100000.0, "total_assets": 100000.0, "portfolio": ["GLD"], "positions": {}
        }).execute(); st.rerun()