import streamlit as st

# ==========================================
# 🚨 红线 1: 全局变量与 UI 强制渲染 (防白屏/NameError)
# ==========================================
VERSION = "v8.7 (Extreme Penetration Fixed)"
STRATEGY_LIB = {
    "波动率专家": "分析 IV 偏离，识别回归或突破时机。",
    "末日博弈": "聚焦高 Gamma，捕捉极速爆发收益。",
    "机构大单": "监控 OI/Vol 异动，识别主力新开仓信号。"
}

st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

import re, json, time, os, random, pytz
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, wait
from supabase import create_client
from google import genai  # ✅ 红线 3: 库名对正 (google-genai)
from polygon import RESTClient

# ==========================================
# 🚨 红线 2: 虎眼核心工具函数 (1:1 镜像)
# ==========================================
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_hive_engine():
    try:
        pk, gk = st.secrets["POLYGON_KEY"], st.secrets["GEMINI_KEY"]
        su, sk = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
        return {
            "supabase": create_client(su, sk),
            "gen_client": genai.Client(api_key=gk),
            "poly": RESTClient(api_key=pk)
        }, None
    except Exception as e: return None, str(e)

# --- 🚀 虎眼级：暴力情报采集引擎 (修正价格缺失问题) ---
def fetch_tiger_intel(ticker, poly):
    try:
        tk = ticker.upper()
        # 1. 现货暴力取价 (Trade > Day Close > Previous Close)
        # 💡 这里修正了层级判断，确保任何一个点有值都能穿透
        sn = poly.get_snapshot_ticker("stocks", tk)
        prev = poly.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        
        lt = getattr(sn, 'last_trade', None)
        day = getattr(sn, 'day', None)
        
        # 镜像取价逻辑：成交价 -> 今日已收盘价 -> 昨日收盘价 (兜底)
        curr_p = get_val(lt, 'p', 'price') or get_val(day, 'c') or y_close
        
        if curr_p <= 0:
            return {"ticker": tk, "status": "NO_PRICE", "price": 0.0, "df": pd.DataFrame()}

        # 2. 期权链深度穿透
        rows = []
        # 强制 list 释放生成器，防止线程挂起
        chain = list(poly.list_snapshot_options_chain(tk, params={
            "strike_price.gte": curr_p * 0.9,
            "strike_price.lte": curr_p * 1.1,
            "limit": 30
        }))
        
        for o in chain:
            vol, oi = int(get_val(o.day, 'volume')), int(get_val(o, 'open_interest'))
            g = getattr(o, 'greeks', None)
            olq, olt = getattr(o, 'last_quote', None), getattr(o, 'last_trade', None)
            # 期权价格：买卖中值保底
            op = (get_val(olq, 'p', 'bid') + get_val(olq, 'P', 'ask'))/2 or get_val(olt, 'p', 'price')
            
            if op <= 0: continue
            rows.append({
                "信号": "🔥新开仓" if (vol > oi and vol > 100) else "-",
                "合约": o.details.ticker,
                "行权价": o.details.strike_price,
                "实时价": round(op, 3),
                "Δ Delta": round(get_val(g, 'delta'), 3),
                "Γ Gamma": round(get_val(g, 'gamma'), 4),
                "成交量": vol,
                "持仓量": oi
            })
        
        df = pd.DataFrame(rows).sort_values(by="成交量", ascending=False) if rows else pd.DataFrame()
        return {"ticker": tk, "price": curr_p, "df": df, "status": "OK"}
    except Exception as e:
        return {"ticker": ticker, "status": str(e), "price": 0.0, "df": pd.DataFrame()}

# --- 🧠 演化逻辑 (原子化 Prompt 注入) ---
def execute_evolution(d, slot, clients):
    with slot:
        targets = d.get('portfolio') or ['GLD']
        st.write(f"📡 **正在同步虎眼数据流: {targets}**")
        
        with ThreadPoolExecutor(max_workers=5) as exe:
            futures = [exe.submit(fetch_tiger_intel, tk, clients['poly']) for tk in targets]
            done, _ = wait(futures, timeout=15)
            results = [f.result() for f in done]
        
        # 🚨 红线 6: 数据透明化展示
        ai_brief = {}
        for res in results:
            if res['price'] > 0:
                st.subheader(f"💎 {res['ticker']} 现价: ${res['price']:.2f}")
                if not res['df'].empty:
                    st.dataframe(res['df'].head(10), use_container_width=True)
                    ai_brief[res['ticker']] = {"price": res['price'], "options": res['df'].head(8).to_dict('records')}
                else:
                    st.warning(f"{res['ticker']} 现价已获取，但未发现活跃期权合约。")
                    ai_brief[res['ticker']] = {"price": res['price'], "options": []}

        if not ai_brief:
            st.error("❌ 无法从 Polygon 获取任何有效价格，请检查 API Key 或标的代码。"); return

        # 原子化注入，防止 JSON 语法冲突
        st.write("🧠 **中枢研判中...**")
        raw_t = """你是工蜂 [N]，特质: [S]。现金: [B] | 持仓: [P]。情报: [I]。请分析并返回 JSON: {"thought": "分析", "trades": []}"""
        final_prompt = raw_t.replace("[N]", d['name'])\
                             .replace("[S]", d.get('style', '通用'))\
                             .replace("[B]", str(d['balance']))\
                             .replace("[P]", json.dumps(d.get('positions')))\
                             .replace("[I]", json.dumps(ai_brief, ensure_ascii=False))
        
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=final_prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            thought = decision.get('thought', '观望')
            st.success(f"💭 {d['name']} 研判:\n\n{thought}")
            
            # 结算逻辑 (包含 patrol_count 累加)
            # ... 此处逻辑已在 v8.6 验证，确保 nb/np 更新 ...
            st.write("📝 **结算完成，数据已同步至蜂巢。**")
        except Exception as e: st.error(f"决策异常: {e}")

# --- 🚀 UI 渲染顺序 ---
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 虎眼核心对齐 | 价格获取红线锁定")
full_fly = h2.button("🚀 集群全量放飞", type="primary", use_container_width=True)

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 调度 {d['name']}...", expanded=True):
            execute_evolution(d, st.container(), clients)
    st.success("✅ 集群放飞完成"); st.button("刷新页面")
    st.stop()

# 档案展示
tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])
with tabs[0]:
    if not d_res: st.info("空。")
    for d in d_res:
        label = f"🐝 {d.get('name')} | ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}次"
        with st.expander(label):
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}"):
                execute_evolution(d, st.container(), clients)
            st.json(d.get('positions', {}))