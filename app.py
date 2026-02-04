import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os, random
from datetime import datetime, timezone
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 神经中枢：模型名精准探测 ---
# 优先级说明：1.5-flash 是目前平衡速度与复杂 JSON 处理的最佳选择
MODEL_CANDIDATES = [
    "gemini-1.5-flash", 
    "gemini-1.5-flash-001", 
    "gemini-1.5-flash-latest",
    "gemini-2.0-flash-exp"
]

@st.cache_resource
def anchor_active_brain():
    """在启动时自动探测可用的模型名"""
    gk = os.environ.get("GEMINI_KEY") or st.secrets.get("GEMINI_KEY")
    client = genai.Client(api_key=gk)
    for model in MODEL_CANDIDATES:
        try:
            # 发起微型握手测试
            client.models.generate_content(model=model, contents="ping")
            return model
        except:
            continue
    return "gemini-1.5-pro" # 终极保底

# --- 2. 蜂群环境初始化 ---
try:
    S_URL = os.environ.get("SUPABASE_URL") or st.secrets.get("SUPABASE_URL")
    S_KEY = os.environ.get("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY")
    G_KEY = os.environ.get("GEMINI_KEY") or st.secrets.get("GEMINI_KEY")
    P_KEY = os.environ.get("POLYGON_KEY") or st.secrets.get("POLYGON_KEY")
    
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
    
    # 锁定当前可用的大脑
    ACTIVE_BRAIN = anchor_active_brain()
except Exception as e:
    st.error(f"蜂巢中枢连接失败: {e}"); st.stop()

# --- 3. 蜜源采集引擎 (多维特征提取) ---
def get_val(obj, *keys):
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

def fetch_nectar(ticker, needs_options=True):
    try:
        sn = poly_client.get_snapshot_ticker("stocks", ticker)
        price = get_val(sn, 'price', 'c')
        if price == 0: price = get_val(sn.last_trade, 'p') if hasattr(sn, 'last_trade') else get_val(sn.prev_day, 'c')
        
        data = {"代码": ticker, "现价": price, "涨跌幅": get_val(sn, 'todays_change_percent')}

        if needs_options and price > 0:
            # 模拟虎之眼：锁定核心交易区 ±15% Strike
            opts = list(poly_client.list_snapshot_options_chain(
                ticker, params={"strike_price.gte": price*0.85, "strike_price.lte": price*1.15, "limit": 15}
            ))
            rows, cv, pv = [], 0, 0
            for o in opts:
                vol = int(get_val(o.day, 'v'))
                if vol < 5: continue
                if o.details.contract_type == 'call': cv += vol
                else: pv += vol
                rows.append({
                    "行权价": o.details.strike_price, 
                    "现价": get_val(o.last_trade, 'p'), 
                    "成交量": vol, 
                    "类型": o.details.contract_type
                })
            data["期权数据"] = {
                "PCR": round(pv/(cv + 1e-5), 2),
                "异动信号": sorted(rows, key=lambda x: x['成交量'], reverse=True)[:5]
            }
        return data
    except:
        return {"代码": ticker, "现价": 0, "状态": "数据链路中断"}

# --- 4. 演化任务引擎 ---
def execute_evolution_cycle(d):
    t_start = time.time()
    with st.status(f"🐝 工蜂 [{d['name']}] 任务执行中...", expanded=True) as status:
        try:
            # 1. 嗅探
            status.write("📡 正在穿透市场嗅探蜜源价格...")
            is_opt_bee = "期权" in (d.get('logic','') + d.get('persona',''))
            
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(lambda t: fetch_nectar(t, is_opt_bee), d.get('portfolio', ['GLD'])))
            
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            
            # 2. 研判
            status.write(f"🧠 咨询神经中枢 (当前大脑: `{ACTIVE_BRAIN}`)...")
            prompt = f"你是工蜂{d['name']}。性格:{d['persona']}。可用本金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data, ensure_ascii=False)}。返回纯JSON：{{'trades':[], 'thought':'中文想法', 'learning':'演化记忆'}}"
            
            r = gen_client.models.generate_content(
                model=ACTIVE_BRAIN, 
                contents=prompt, 
                config={'response_mime_type': 'application/json'}
            )
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]

            # 3. 结算
            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker', t.get('symbol', '')), t.get('qty', 0), t.get('action', '').upper()
                if not sym or qty <= 0: continue
                px = fetch_nectar(sym, False)['现价']
                cost = float(qty) * float(px) * (100 if "O:" in sym else 1)
                
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym} @{px}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴卖出 {sym} @{px}")

            # 4. 同步
            mv = 0.0
            for s, q in np.items(): mv += q * fetch_nectar(s, False)['现价'] * (100 if "O:" in s else 1)
            
            log_str = f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '观望')} | 🧠[{ACTIVE_BRAIN}] {decision.get('thought','')}"
            
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + mv, 2),
                "logs": ([log_str] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
                "memory": decision.get('learning', d.get('memory'))
            }).eq("id", d["id"]).execute()
            
            status.update(label=f"✅ 任务完成 (耗时: {time.time()-t_start:.2f}s)", state="complete")
            return True
        except Exception as e:
            status.update(label=f"❌ 运行异常: {str(e)}", state="error"); return False

# --- 5. UI 控制台 ---
st.title("🐝 Hive 蜂群生态控制台")
st.info(f"🧬 当前神经中枢已锚定最快大脑: `{ACTIVE_BRAIN}`")

t1, t2, t3 = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 蜂巢维护"])

with t1:
    d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data
    
    col_l, col_r = st.columns([3, 1])
    col_l.subheader(f"在线工蜂: {len(d_res or [])}")
    if d_res and col_r.button("🔥 全量放飞", type="primary", use_container_width=True):
        for d in d_res: execute_evolution_cycle(d); time.sleep(0.4)
        st.rerun()

    for d in (d_res or []):
        with st.expander(f"🐝 {d['name']} | 总资产: ${d.get('total_assets', 0):,.2f}"):
            c1, c2, c3 = st.columns(3)
            c1.info(f"🎭 **性格基因**\n\n{d['persona']}")
            c2.info(f"🧬 **逻辑蓝图**\n\n{d['logic']}")
            c3.info(f"💾 **演化记忆**\n\n{d['memory']}")
            if st.button(f"🚀 立即放飞", key=f"run_{d['id']}"):
                execute_evolution_cycle(d); st.rerun()
            st.metric("可用现金", f"${d['balance']:,.2f}")
            if d.get('positions'): st.json(d['positions'])
            for l in (d.get('logs') or [])[:5]: st.caption(l)

with t2:
    instr = st.text_area("输入孵化指令:")
    if st.button("开始孵化"):
        p = f"设计工蜂。返回纯JSON：{{'name':'','logic':'','persona':'','portfolio':['GLD']}}。指令：{instr}"
        r = gen_client.models.generate_content(model=ACTIVE_BRAIN, contents=p)
        item = json.loads(r.text.replace("```json","").replace("```","").strip())
        item.update({"balance": 100000.0, "total_assets": 100000.0, "created_at": datetime.now(timezone.utc).isoformat(), "logs": ["诞生于蜂巢"], "positions": {}})
        supabase.table("drones").insert(item).execute(); st.rerun()

with t3:
    if st.button("🔥 清空蜂巢"):
        supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()