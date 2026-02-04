import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os
from datetime import datetime, timezone
from google import genai
from polygon import RESTClient

# --- 1. 配置加载 ---
try:
    S_URL, S_KEY = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
    G_KEY, P_KEY = st.secrets["GEMINI_KEY"], st.secrets["POLYGON_KEY"]
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
    MODEL_ID = "gemini-3-flash-preview"
except Exception as e:
    st.error(f"密钥配置异常: {e}")
    st.stop()

# --- 2. 安全提取器 (防止 NoneType 报错的核心) ---
def get_safe(obj, path, default=0):
    try:
        for p in path.split("."): 
            obj = getattr(obj, p)
        return obj if obj is not None else default
    except: return default

# --- 3. 盘前数据采集 (支持静默失败) ---
def get_market_data(tickers):
    context = {}
    now = datetime.now()
    # 过滤掉非法 Ticker，确保只请求真实的股票代码
    valid_ts = [t for t in tickers if t.isalpha() and len(t) <= 5] or ["GLD"]
    
    for t in valid_ts:
        try:
            sn = poly_client.get_snapshot_ticker("stocks", t)
            # 盘前价格获取逻辑：优先实时，次之昨收
            price = get_safe(sn, "last_trade.p", get_safe(sn, "prev_day.c", 0))
            
            all_opts = []
            try:
                # 尝试拉取期权，盘前若 NotFound 会跳入 except，不会崩
                chain = poly_client.list_snapshot_options_chain(t, params={"limit": 50})
                for o in chain:
                    o_px = get_safe(o, "last_trade.p", get_safe(o, "day.c", 0))
                    if o_px > 0:
                        all_opts.append({
                            "ticker": o.ticker, "strike": o.details.strike_price,
                            "price": o_px, "vol": get_safe(o, "day.v", 0),
                            "days": (datetime.strptime(o.ticker[5:11], "%y%m%d") - now).days
                        })
            except: pass # 盘前期权数据缺失属正常情况

            # 分时采样（短/中/长）
            buckets = {"short": [], "mid": [], "long": []}
            for o in all_opts:
                if o["days"] <= 14: buckets["short"].append(o)
                elif 30 <= o["days"] <= 60: buckets["mid"].append(o)
                elif o["days"] >= 150: buckets["long"].append(o)

            final_opts = []
            for b in buckets: final_opts.extend(sorted(buckets[b], key=lambda x: x['vol'], reverse=True)[:5])
            context[t] = {"price": price, "options": final_opts}
        except: context[t] = {"price": 0, "options": []}
    return context

# --- 4. 演化引擎 ---
def evolve_drone(d):
    try:
        m_data = get_market_data(d.get('portfolio', ['GLD']))
        # 即使 options 为空，AI 也会看到正股价格并决定是否操作正股
        prompt = f"你是工蜂{d['name']}。性格:{d['persona']}。余额:{d['balance']}。行情:{json.dumps(m_data)}。请决策。返回JSON：{{'trades':[], 'thought':'', 'learning':''}}"
        
        r = gen_client.models.generate_content(model=MODEL_ID, contents=prompt, config={'response_mime_type': 'application/json'})
        cmd = json.loads(r.text)
        if isinstance(cmd, list): cmd = cmd[0]

        nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
        
        for t in cmd.get('trades', []):
            sym = t.get('symbol', t.get('ticker', ''))
            qty = t.get('qty', t.get('quantity', 0))
            if not sym or qty <= 0: continue
            
            # 实时锁价逻辑
            p_obj = poly_client.get_last_trade(sym)
            px = get_safe(p_obj, "price", get_safe(p_obj, "p", t.get('price', 0)))
            if px == 0:
                sn = poly_client.get_snapshot_ticker("stocks" if "O:" not in sym else "options", sym)
                px = get_safe(sn, "last_trade.p", get_safe(sn, "prev_day.c", 0))

            cost = float(qty) * float(px) * (100 if "O:" in sym else 1)
            act = t.get('action', '').upper()
            if act == 'BUY' and nb >= cost:
                nb -= cost; np[sym] = np.get(sym, 0) + qty
                reports.append(f"🟢买入 {sym} @{px}")
            elif act == 'SELL' and np.get(sym, 0) >= qty:
                nb += cost; np[sym] -= qty
                if np[sym] <= 0: del np[sym]
                reports.append(f"🔴卖出 {sym} @{px}")

        # 资产重估
        mv = 0.0
        for s, q in np.items():
            try:
                p_obj = poly_client.get_last_trade(s)
                sp = get_safe(p_obj, "price", 0)
                if sp == 0:
                    sn = poly_client.get_snapshot_ticker("stocks" if "O:" not in s else "options", s)
                    sp = get_safe(sn, "last_trade.p", get_safe(sn, "prev_day.c", 0))
                mv += q * sp * (100 if "O:" in s else 1)
            except: pass

        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log_str = f"[{ts}] {(' | '.join(reports) if reports else '🟡观望')} | 🧠 {cmd.get('thought','')}"
        
        supabase.table("drones").update({
            "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
            "logs": ([log_str] + (d.get('logs') or []))[:20],
            "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
            "memory": cmd.get('learning', d.get('memory'))
        }).eq("id", d["id"]).execute()
        return True
    except Exception as e:
        st.error(f"演化异常: {e}"); return False

# --- 5. UI 界面 ---
st.title("🐝 Hive 蜂巢实时控制台")
t1, t2, t3 = st.tabs(["🏆 工蜂列表", "👑 蜂后孵化", "⚙️ 系统管理"])

with t1:
    res = supabase.table("drones").select("*").order("created_at", desc=True).execute()
    for d in (res.data or []):
        age_td = datetime.now(timezone.utc) - datetime.fromisoformat(d['created_at'].replace('Z', '+00:00'))
        age_str = f"{age_td.days}d {age_td.seconds // 3600}h"
        
        with st.expander(f"🐝 {d['name']} | 资产: ${d.get('total_assets', 0):,.2f} | 寿命: {age_str}"):
            # 档案卡
            c1, c2, c3 = st.columns(3)
            c1.info(f"🎭 性格: {d.get('persona', '未设定')}")
            c2.info(f"🧬 逻辑: {d.get('logic', '标准')}")
            c3.info(f"💾 记忆: {d.get('memory', '空白')}")
            
            col_btn, col_val = st.columns([1, 2])
            if col_btn.button(f"🚀 立即演化", key=d['id']):
                if evolve_drone(d): st.success("资产同步成功！"); time.sleep(1); st.rerun()
            
            col_val.metric("当前现金", f"${d['balance']:,.2f}")
            if d.get('positions'): st.json(d['positions'])
            for l in (d.get('logs') or [])[:5]: st.caption(l)

with t2:
    instr = st.text_area("孵化指令 (建议：正股+期权混搭):")
    if st.button("开始孵化"):
        p = f"设计工蜂。返回纯JSON列表：[{{'name':'','logic':'','persona':'','balance':100000,'portfolio':['GLD']}}]。指令：{instr}"
        r = gen_client.models.generate_content(model=MODEL_ID, contents=p, config={'response_mime_type': 'application/json'})
        for item in json.loads(r.text):
            item.update({"created_at": datetime.now(timezone.utc).isoformat(), "logs": [], "total_assets": 100000.0, "positions": {}, "memory": "出生"})
            supabase.table("drones").insert(item).execute()
        st.rerun()

with t3:
    if st.button("🔥 全量清空"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()