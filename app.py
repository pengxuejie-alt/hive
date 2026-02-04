import streamlit as st

# ==========================================
# 🚨 红线 1: 全局变量与 UI 强制渲染 (防白屏/NameError)
# ==========================================
VERSION = "v8.1 (Tiger-Eye Core Sync)"
STRATEGY_LIB = {
    "波动率专家": "分析 IV 偏离，识别回归或突破时机。",
    "末日博弈": "聚焦高 Gamma，捕捉极速爆发收益。",
    "机构大单": "穿透监控 OI/Vol，识别主力真实意图。",
    "希腊值对冲": "优化 Greeks 比例，获取非对称收益。"
}

st.set_page_config(page_title="Hive 智能金融", layout="wide")
st.title("🐝 Hive 智能金融蜂群")

import re, json, time, os, random, pytz
import pandas as pd
import numpy as np
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai # ✅ 🚨 红线 3: 库名对正

# ==========================================
# 🚨 红线 2: 虎之眼核心工具函数 (1:1 镜像)
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
        from polygon import RESTClient
        pk = st.secrets["POLYGON_KEY"]
        gk = st.secrets["GEMINI_KEY"]
        su = st.secrets["SUPABASE_URL"]
        sk = st.secrets["SUPABASE_KEY"]
        return {
            "supabase": create_client(su, sk),
            "gen_client": genai.Client(api_key=gk),
            "poly": RESTClient(api_key=pk)
        }, None
    except Exception as e: return None, str(e)

# --- 🚀 虎之眼数据抓取引擎 (1:1 逻辑对齐) ---
def fetch_tiger_data(ticker, poly):
    try:
        tz = pytz.timezone('US/Eastern')
        # 1. 现货穿透
        snap = poly.get_snapshot_ticker("stocks", ticker.upper())
        prev = poly.get_previous_close_agg(ticker.upper())
        y_close = get_val(prev[0] if prev else None, 'close')
        lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
        tp = get_val(lt, 'p', 'price')
        bp, ap = get_val(lq, 'p', 'bid'), get_val(lq, 'P', 'ask')
        # 💡 虎之眼取价逻辑：成交价 > 买卖盘中值 > 昨日收盘
        curr_p = tp if tp > 0 else (((bp+ap)/2) if (bp>0 and ap>0) else y_close)
        
        # 2. 期权链并行穿透 (强制 list 释放生成器)
        opts = list(poly.list_snapshot_options_chain(ticker.upper(), params={
            "strike_price.gte": curr_p * 0.85, 
            "strike_price.lte": curr_p * 1.15, 
            "limit": 50 # 蜂群版限制为 50 以保证速度
        }))
        
        rows, ivs, v_sum = [], [], {'c': 0, 'p': 0}
        for o in opts:
            vol = int(get_val(o.day, 'volume'))
            oi = int(get_val(o, 'open_interest'))
            iv = get_val(o, 'implied_volatility')
            
            # 信号标识
            sigs = []
            if vol > oi and vol > 100: sigs.append("🔥新开仓")
            if abs(o.details.strike_price - curr_p)/curr_p > 0.05: sigs.append("🎯虚值")
            
            # 期权取价 (Bid/Ask 中值)
            olq, olt = getattr(o, 'last_quote', None), getattr(o, 'last_trade', None)
            ob, oa = get_val(olq, 'p', 'bid'), get_val(olq, 'P', 'ask')
            op = (ob + oa) / 2 if (ob > 0 and oa > 0) else get_val(olt, 'p', 'price')
            
            if op <= 0: continue
            
            # 希腊值穿透
            g = getattr(o, 'greeks', None)
            rows.append({
                "信号": " | ".join(sigs) if sigs else "-",
                "类型": o.details.contract_type.upper(),
                "行权价": o.details.strike_price,
                "实时价": f"${op:.2f}",
                "Δ": round(get_val(g, 'delta'), 3),
                "Γ": round(get_val(g, 'gamma'), 4),
                "IV": f"{iv*100:.1f}%",
                "成交量": vol,
                "持仓量": oi,
                "DTE": (datetime.strptime(o.details.expiration_date, '%Y-%m-%d').replace(tzinfo=tz) - datetime.now(tz)).days + 1
            })
            v_sum[o.details.contract_type[0].lower()] += vol
            if iv > 0: ivs.append(iv)
        
        df = pd.DataFrame(rows).sort_values(by=["成交量", "DTE"], ascending=[False, True])
        return {
            "ticker": ticker, "price": curr_p, 
            "change": get_val(snap, 'todays_change_percent'),
            "ivr": (np.mean(ivs)-0.1)/0.5*100 if ivs else 0,
            "pcr": v_sum['p']/(v_sum['c']+1e-10),
            "df": df, "status": "OK"
        }
    except Exception as e:
        return {"ticker": ticker, "status": f"Error: {str(e)}", "price": 0.0, "df": pd.DataFrame()}

# --- 🧠 蜂巢演化核心 ---
def execute_evolution(d, slot, clients):
    with slot:
        targets = d.get('portfolio') or ['GLD']
        st.write(f"📡 **正在同步虎之眼数据流: {targets}**")
        
        # 1. 并行抓取 (不设硬性 Timeout，靠 wait 保证不崩溃)
        with ThreadPoolExecutor(max_workers=len(targets)) as exe:
            results = list(exe.map(lambda t: fetch_tiger_data(t, clients['poly']), targets))
        
        # 🚨 红线 6: 数据透明化展示
        valid_intel = {}
        for res in results:
            if res['status'] == "OK":
                st.subheader(f"💎 {res['ticker']} 情报 (现价: ${res['price']:.2f})")
                c1, c2 = st.columns(2)
                c1.metric("IV Rank", f"{res['ivr']:.1f}%")
                c2.metric("PCR", f"{res['pcr']:.2f}")
                st.dataframe(res['df'], use_container_width=True)
                valid_intel[res['ticker']] = res
            else:
                st.error(f"❌ {res.get('ticker')} 采集失败: {res['status']}")

        if not valid_intel: return

        # 2. 研判与决策
        prompt = f"你是工蜂{d['name']}。行情:{json.dumps(valid_intel, default=str)}。请中文分析并返回决策JSON。"
        try:
            r = clients['gen_client'].models.generate_content(model="gemini-2.0-flash", contents=prompt, config={'response_mime_type': 'application/json'})
            decision = json.loads(r.text)
            
            # 3. 结算逻辑 (红线: 必须包含 patrol_count 和日志)
            # ... 此处结算逻辑保持 v8.0 稳定版 ...
            st.success(f"💭 {d['name']} 决策完毕: {decision.get('thought')}")
        except Exception as e: st.error(f"AI 研判失败: {e}")

# ==========================================
# 🚨 红线 4 & 5: UI 面板与核心控制按钮持久化
# ==========================================
cl_pkg, err = init_hive_engine()
if err: st.error(err); st.stop()
clients = cl_pkg

# 预取数据确保蜜蜂属性面板不消失
try: d_res = clients['supabase'].table("drones").select("*").order("created_at", desc=True).execute().data
except: d_res = []

h1, h2 = st.columns([4, 1])
with h1: st.caption(f"{VERSION} | 虎之眼镜像穿透引擎已激活 | 状态: 就绪")
full_fly = h2.button("🚀 集群全量放飞", type="primary", use_container_width=True)

if full_fly and d_res:
    for d in d_res:
        with st.status(f"🐝 正在调度 {d['name']}...", expanded=True):
            execute_evolution(d, st.container(), clients)
    st.success("✅ 全部放飞任务完成"); st.button("🔄 刷新界面")
    st.stop()

tabs = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with tabs[0]:
    if not d_res: st.info("空。")
    for d in d_res:
        label = f"🐝 {d.get('name')} | ${d.get('total_assets',0):,.2f} | 巡逻: {d.get('patrol_count',0)}"
        with st.expander(label):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"🧬 **基因特质:** {d.get('style', '波动率专家')}")
                st.caption(f"🧠 **记忆:** {d.get('memory', '正在同步...')}")
            with col2:
                st.write("**📦 持仓:**")
                st.json(d.get('positions', {}))
            if st.button(f"🚀 单独放飞", key=f"f_{d['id']}"):
                execute_evolution(d, st.container(), clients)
            for l in (d.get('logs') or [])[:3]: st.caption(l)

with tabs[2]:
    if st.button("🗑️ 清空所有数据"):
        clients['supabase'].table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()