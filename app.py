import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os, random
from datetime import datetime, timezone
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 蜂群中枢配置 ---
def get_config(key): return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    G_KEY, P_KEY = get_config("GEMINI_KEY"), get_config("POLYGON_KEY")
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
    
    # 神经元集群（备选模型，用于降级与加速）
    NEURON_CLUSTERS = ["gemini-1.5-flash", "gemini-2.0-flash-exp", "gemini-1.5-pro"]
except Exception as e:
    st.error(f"中枢连接失败: {e}"); st.stop()

# --- 2. 蜜源采集引擎 (针对虎之眼优化) ---
def get_val(obj, *keys):
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

def fetch_nectar_pro(ticker, needs_options=True):
    """蜜源采集：获取正股与关键期权特征，对齐虎之眼并行逻辑"""
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        price = get_val(sn, 'price', 'c')
        if price == 0: price = get_val(sn.last_trade, 'p') if hasattr(sn, 'last_trade') else get_val(sn.prev_day, 'c')
        
        data = {"代码": ticker, "现价": price, "涨跌": get_val(sn, 'todays_change_percent'), "成交量": get_val(sn.day, 'v')}

        if needs_options and price > 0:
            # 锁定核心交易区：±15% Strike，采样活跃合约
            opts = list(poly_client.list_snapshot_options_chain(
                ticker, params={"strike_price.gte": price*0.85, "strike_price.lte": price*1.15, "limit": 25}
            ))
            rows, call_v, put_v = [], 0, 0
            for o in opts:
                vol = int(get_val(o.day, 'volume', 'v'))
                oi = int(get_val(o, 'open_interest', 'oi'))
                op = get_val(o.last_trade, 'p') if hasattr(o, 'last_trade') else get_val(o.day, 'c')
                if op <= 0 or vol < 5: continue
                
                if o.details.contract_type == 'call': call_v += vol
                else: put_v += vol

                sigs = []
                if vol > oi and vol > 100: sigs.append("🔥主力开仓")
                if vol > 500: sigs.append("🐋大单异动")
                rows.append({"S": o.details.strike_price, "P": op, "V": vol, "信号": sigs, "类型": o.details.contract_type})

            data["期权数据"] = {
                "PCR": round(put_v/(call_v + 1e-5), 2),
                "异动信号": sorted(rows, key=lambda x: x['V'], reverse=True)[:8]
            }
        return data
    except: return {"代码": ticker, "现价": 0, "状态": "接口超时"}

# --- 3. 神经决策调度 ---
def consult_neuro_center(prompt):
    for cluster in NEURON_CLUSTERS:
        for i in range(2):
            try:
                r = gen_client.models.generate_content(model=cluster, contents=prompt, config={'response_mime_type': 'application/json'})
                return json.loads(r.text), cluster
            except:
                time.sleep(1); continue
    return None, "Offline"

# --- 4. 演化任务 ---
def execute_worker_cycle(d):
    t_start = time.time()
    with st.status(f"🐝 工蜂 [{d['name']}] 任务执行中...", expanded=True) as status:
        try:
            # 1. 嗅探蜜源
            status.write("📡 正在并发穿透市场嗅探蜜源价格...")
            logic_str = (d.get('logic','') + d.get('persona','')).lower()
            needs_opts = any(x in logic_str for x in ["期权", "option", "iv", "hedge"])
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(lambda t: fetch_nectar_pro(t, needs_opts), d.get('portfolio', ['GLD'])))
            
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            status.write(f"📍 行情采集完成 (耗时: {time.time()-t_start:.2f}s)")
            
            # 2. 神经研判
            s2_t = time.time()
            prompt = f"你是工蜂{d['name']}。性格:{d['persona']}。余额:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data, ensure_ascii=False)}。返回JSON：{{'trades':[], 'thought':'中文想法', 'learning':'演化记忆'}}"
            decision, neuro_id = consult_neuro_center(prompt)
            if not decision: raise Exception("大脑响应超时")
            status.write(f"🧠 神经元 `{neuro_id}` 完成研判 (耗时: {time.time()-s2_t:.2f}s)")

            # 3. 资产清算与执行
            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker', t.get('symbol', '')), t.get('qty', 0), t.get('action', '').upper()
                if not sym or qty <= 0: continue
                px = fetch_nectar_pro(sym, False)['现价']
                cost = float(qty) * float(px) * (100 if "O:" in sym else 1)
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym} @{px}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴卖出 {sym} @{px}")

            # 4. 蜂房入库
            mv = 0.0
            for s, q in np.items(): mv += q * fetch_nectar_pro(s, False)['现价'] * (100 if "O:" in s else 1)
            
            log_str = f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')} | 🧠[{neuro_id}] {decision.get('thought','')}"
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
                "memory": decision.get('learning', d.get('memory'))
            }).eq("id", d["id"]).execute()
            
            status.write(f"🏁 **总耗时: {time.time()-t_start:.2f}s**")
            return True
        except Exception as e:
            status.write(f"❌ 运行异常: {str(e)}")
            return False

# --- 5. 蜂群控制台 UI ---
st.title("🐝 Hive 蜂群生态系统")
st.caption(f"🧠 神经中枢状态: {', '.join([f'`{m}`' for m in NEURON_CLUSTERS])}")

t1, t2, t3 = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统维护"])

with t1:
    d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data
    col_l, col_r = st.columns([4, 1])
    col_l.subheader(f"在线工蜂: {len(d_res or [])}")
    if d_res and col_r.button("🔥 一键放飞全部", type="primary", use_container_width=True):
        for d in d_res: execute_worker_cycle(d); time.sleep(0.5)
        st.rerun()

    for d in (d_res or []):
        with st.expander(f"🐝 {d['name']} | 总资产: ${d.get('total_assets', 0):,.2f}"):
            c1, c2, c3 = st.columns(3)
            c1.info(f"🎭 **性格基因**\n\n{d['persona']}")
            c2.info(f"🧬 **逻辑蓝图**\n\n{d['logic']}")
            c3.info(f"💾 **演化记忆**\n\n{d['memory']}")
            
            btn_col, val_col = st.columns([1, 3])
            if btn_col.button(f"🚀 立即放飞", key=f"run_{d['id']}"):
                execute_worker_cycle(d); st.rerun()
            
            val_col.metric("可用现金", f"${d['balance']:,.2f}")
            if d.get('positions'): st.json(d['positions'])
            st.divider()
            for l in (d.get('logs') or [])[:5]: st.caption(l)

with t2:
    st.subheader("👑 蜂后孵化指令")
    instr = st.text_area("输入中文基因指令:")
    if st.button("开始孵化"):
        p = f"设计工蜂。返回纯JSON：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。指令：{instr}"
        res, _ = consult_neuro_center(p)
        res.update({"balance": 100000.0, "total_assets": 100000.0, "created_at": datetime.now(timezone.utc).isoformat(), "logs": ["诞生"], "positions": {}})
        supabase.table("drones").insert(res).execute(); st.rerun()

with t3:
    if st.button("🔥 清空蜂巢"): supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()