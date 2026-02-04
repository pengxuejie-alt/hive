import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os
from datetime import datetime, timezone
from google import genai
from polygon import RESTClient

# --- 1. 配置与接入 ---
st.set_page_config(page_title="Hive 实时控制台", layout="wide", page_icon="🐝")

try:
    # 优先从 st.secrets 读取，兼容 Streamlit Cloud 环境
    S_URL = st.secrets["SUPABASE_URL"]
    S_KEY = st.secrets["SUPABASE_KEY"]
    G_KEY = st.secrets["GEMINI_KEY"]
    P_KEY = st.secrets["POLYGON_KEY"]
    
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
    MODEL_ID = "gemini-3-flash-preview"
except Exception as e:
    st.error(f"启动配置失败: {e}")
    st.stop()

# --- 2. 核心行情采集逻辑 (从 Worker 迁移) ---
def get_safe_val(obj, path, default=0):
    try:
        for part in path.split("."): obj = getattr(obj, part)
        return obj if obj is not None else default
    except: return default

def get_market_data_smart(tickers):
    context = {}
    now = datetime.now()
    valid_tickers = [t for t in tickers if t.isalpha() and len(t) <= 5]
    if not valid_tickers: valid_tickers = ["GLD"]

    for t in valid_tickers:
        with st.spinner(f"正在扫描 {t} 的多维度行情..."):
            try:
                sn = poly_client.get_snapshot_ticker("stocks", t)
                price = get_safe_val(sn, "last_trade.price", get_safe_val(sn, "prev_day.c"))
                
                chain = poly_client.list_snapshot_options_chain(t, params={"limit": 100})
                buckets = {"short": [], "mid": [], "long": []}
                
                for o in chain:
                    expiry_dt = datetime.strptime(o.ticker[5:11], "%y%m%d")
                    days = (expiry_dt - now).days
                    o_px = get_safe_val(o, "last_trade.price", get_safe_val(o, "day.c"))
                    if o_px <= 0: continue
                    item = {"ticker": o.ticker, "strike": o.details.strike_price, "price": o_px, "vol": get_safe_val(o, "day.v"), "days": days}
                    if days <= 14: buckets["short"].append(item)
                    elif 30 <= days <= 50: buckets["mid"].append(item)
                    elif days >= 150: buckets["long"].append(item)

                final_opts = []
                for b in buckets: final_opts.extend(sorted(buckets[b], key=lambda x: x['vol'], reverse=True)[:5])
                context[t] = {"price": price, "options": final_opts}
            except Exception as e:
                st.warning(f"{t} 采集异常: {e}")
    return context

# --- 3. 实时演化引擎 ---
def evolve_drone(d):
    try:
        m_data = get_market_data_smart(d.get('portfolio', ['GLD']))
        prompt = f"你是工蜂{d['name']}。性格:{d['persona']}。余额:{d['balance']}。行情:{json.dumps(m_data)}。返回JSON：{{'trades':[], 'thought':'', 'learning':''}}"
        
        r = gen_client.models.generate_content(model=MODEL_ID, contents=prompt, config={'response_mime_type': 'application/json'})
        cmd = json.loads(r.text)
        if isinstance(cmd, list): cmd = cmd[0]

        new_bal, new_pos, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
        
        for t in cmd.get('trades', []):
            sym = t.get('symbol', t.get('ticker', ''))
            qty = t.get('qty', t.get('quantity', 0))
            if not sym or qty <= 0: continue
            
            p_obj = poly_client.get_last_trade(sym)
            current_p = get_safe_val(p_obj, "price", t.get('price', 0))
            cost = float(qty) * float(current_p) * (100 if "O:" in sym else 1)
            
            action = t.get('action', '').upper()
            if action == 'BUY' and new_bal >= cost:
                new_bal -= cost
                new_pos[sym] = new_pos.get(sym, 0) + qty
                reports.append(f"🟢买入 {sym} @{current_p}")
            elif action == 'SELL' and new_pos.get(sym, 0) >= qty:
                new_bal += cost
                new_pos[sym] -= qty
                if new_pos[sym] <= 0: del new_pos[sym]
                reports.append(f"🔴卖出 {sym} @{current_p}")

        # 资产重估
        mv = 0.0
        for s, q in new_pos.items():
            p_obj = poly_client.get_last_trade(s)
            mv += q * get_safe_val(p_obj, "price") * (100 if "O:" in s else 1)

        # 更新数据库
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log_str = f"[{ts}] {(' | '.join(reports) if reports else '🟡观望')} | 🧠 {cmd.get('thought','')}"
        
        supabase.table("drones").update({
            "balance": new_bal, "positions": new_pos, "total_assets": round(new_bal + mv, 2),
            "logs": ([log_str] + (d.get('logs') or []))[:20],
            "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
            "memory": cmd.get('learning', d.get('memory'))
        }).eq("id", d["id"]).execute()
        return True
    except Exception as e:
        st.error(f"{d['name']} 演化失败: {e}")
        return False

# --- 4. UI 界面 ---
t1, t2, t3 = st.tabs(["🏆 工蜂列表", "👑 蜂后孵化", "⚙️ 系统管理"])

with t1:
    drones = supabase.table("drones").select("*").order("created_at", desc=True).execute().data
    if not drones:
        st.info("蜂巢空虚...")
    else:
        for d in drones:
            with st.expander(f"🐝 {d['name']} | 资产: ${d.get('total_assets', 0):,.2f}"):
                # 档案显示
                c1, c2, c3 = st.columns(3)
                c1.caption("🎭 性格"); c1.write(d.get('persona'))
                c2.caption("🧬 逻辑"); c2.write(d.get('logic'))
                c3.caption("💾 记忆"); c3.write(d.get('memory'))
                
                # 手动放飞按钮
                if st.button(f"🚀 单独放飞 {d['name']}", key=f"fly_{d['id']}"):
                    if evolve_drone(d): 
                        st.success("演化成功！")
                        time.sleep(1); st.rerun()

                # 财务数据
                st.metric("现金余额", f"${d['balance']:,.2f}")
                if d.get('positions'): st.json(d['positions'])
                for l in (d.get('logs', []) or [])[:5]: st.caption(l)

with t2:
    instr = st.text_area("孵化指令:", placeholder="例如：孵化3只交易GLD的工蜂...")
    if st.button("开始孵化", type="primary"):
        p = f"设计工蜂。返回纯JSON列表：[{{'name':'','focus':'','portfolio':['GLD'],'logic':'','persona':'','balance':100000}}]。指令：{instr}"
        r = gen_client.models.generate_content(model=MODEL_ID, contents=p, config={'response_mime_type': 'application/json'})
        for item in json.loads(r.text):
            item.update({"created_at": datetime.now(timezone.utc).isoformat(), "logs": [], "total_assets": 100000.0, "positions": {}, "memory": "新生。"})
            supabase.table("drones").insert(item).execute()
        st.success("孵化成功！"); st.rerun()

with t3:
    if st.button("🔥 全量清空蜂巢"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute()
        st.rerun()