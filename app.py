import streamlit as st
import pandas as pd
from supabase import create_client
import json, time, os
from datetime import datetime, timezone
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from google import genai
from polygon import RESTClient

# --- 1. 配置加载 ---
def get_config(key): return os.environ.get(key) or st.secrets.get(key)

try:
    S_URL, S_KEY = get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")
    G_KEY, P_KEY = get_config("GEMINI_KEY"), get_config("POLYGON_KEY")
    supabase = create_client(S_URL, S_KEY)
    gen_client = genai.Client(api_key=G_KEY)
    poly_client = RESTClient(api_key=P_KEY)
    MODEL_ID = "gemini-3-flash-preview"
except Exception as e:
    st.error(f"密钥配置异常: {e}"); st.stop()

# --- 2. 蜂群核心采集引擎 (并行化与按需采样) ---
def get_val(obj, *keys):
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

def fetch_single_ticker(ticker, needs_options=True):
    """单标的穿透函数：对齐虎之眼逻辑，性能优化版"""
    try:
        # A. 正股穿透
        snap = poly_client.get_snapshot_ticker("stocks", ticker)
        price = get_val(snap, 'price', 'c')
        if price == 0:
            price = get_val(snap.last_trade, 'p') if hasattr(snap, 'last_trade') else get_val(snap.prev_day, 'c')
        
        data = {
            "ticker": ticker,
            "price": price,
            "change": get_val(snap, 'todays_change_percent'),
            "vol": get_val(snap.day, 'v')
        }

        # B. 期权深度采样 (仅在工蜂需要时触发)
        if needs_options and price > 0:
            # 锁定平值上下 15% 范围，限制 50 条以保证速度
            opts = list(poly_client.list_snapshot_options_chain(
                ticker, 
                params={"strike_price.gte": price*0.85, "strike_price.lte": price*1.15, "limit": 50}
            ))
            
            rows, ivs, v_sum = [], [], {'c': 0, 'p': 0}
            now = datetime.now()

            for o in opts:
                vol = int(get_val(o.day, 'volume', 'v'))
                oi = int(get_val(o, 'open_interest', 'oi'))
                iv = get_val(o, 'implied_volatility', 'iv')
                strike = o.details.strike_price
                exp_dt = datetime.strptime(o.details.expiration_date, '%Y-%m-%d')
                days = (exp_dt - now).days

                # 提取期权实时价
                op = get_val(o.last_trade, 'p') if hasattr(o, 'last_trade') else get_val(o.day, 'c')
                if op <= 0: continue

                # 捕捉异动信号 (对齐虎之眼)
                sigs = []
                if vol > oi and vol > 100: sigs.append("🔥主力开仓")
                if vol > 500: sigs.append("🐋大单")

                rows.append({
                    "ticker": o.ticker, "strike": strike, "type": o.details.contract_type,
                    "price": op, "vol": vol, "oi": oi, "iv": f"{iv*100:.1f}%", "days": days, "sigs": sigs
                })
                v_sum[o.details.contract_type[0].lower()] += vol
                if iv > 0: ivs.append(iv)

            # 特征封装
            data["options_summary"] = {
                "pcr": round(v_sum['p']/(v_sum['c']+1e-10), 2),
                "avg_iv": f"{np.mean(ivs)*100:.1f}%" if ivs else "0%",
                "top_moves": sorted(rows, key=lambda x: x['vol'], reverse=True)[:10] # 最活跃Top 10
            }
        return data
    except: return {"ticker": ticker, "price": 0, "error": "Fetch Failed"}

# --- 3. 蜂群放飞逻辑 (多线程驱动) ---
def evolve_drone_swarm(d):
    total_start = time.time()
    with st.status(f"🐝 {d['name']} 正在进行多并发演化...", expanded=True) as status:
        try:
            # 步骤 1: 并行行情穿透 (蜂群核心)
            status.write("📡 蜂群正在多线程穿透标的与期权链...")
            portfolio = d.get('portfolio', ['GLD', 'SLV'])
            needs_options = any(w in (d.get('logic','') + d.get('persona','')).lower() for w in ["期权", "option", "iv", "hedge"])
            
            with ThreadPoolExecutor(max_workers=len(portfolio)) as executor:
                results = list(executor.map(lambda t: fetch_single_ticker(t, needs_options), portfolio))
            
            m_data = {r['ticker']: r for r in results if r['price'] > 0}
            status.write(f"📍 行情采集完成 (并发耗时: {time.time()-total_start:.2f}s)")

            # 步骤 2: AI 深度研判 (对齐虎之眼策略逻辑)
            s2_t = time.time()
            prompt = f"""你是{d['name']}。性格:{d['persona']}。
            当前标的数据集: {json.dumps(m_data, ensure_ascii=False)}
            余额: {d['balance']} | 持仓: {json.dumps(d.get('positions'))}
            
            任务：
            1. 跨标的对比 IVR 和 PCR，寻找定价偏离。
            2. 识别 sigs 中带 🔥 和 🐋 的异常期权大单。
            3. 给出基于中文的调仓建议。
            返回标准JSON：{{'trades':[], 'thought':'中文研判', 'learning':'演化心得'}}"""
            
            r = gen_client.models.generate_content(model=MODEL_ID, contents=prompt, config={'response_mime_type': 'application/json'})
            cmd = json.loads(r.text)
            if isinstance(cmd, list): cmd = cmd[0]
            status.write(f"📍 Gemini 大脑研判完成 (耗时: {time.time()-s2_t:.2f}s)")

            # 步骤 3: 锁价与数据库同步
            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in cmd.get('trades', []):
                sym, qty = t.get('ticker', t.get('symbol', '')), t.get('qty', 0)
                if not sym or qty <= 0: continue
                # 实时锁价保底
                px = fetch_single_ticker(sym, False)['price']
                cost = float(qty) * float(px) * (100 if "O:" in sym else 1)
                
                if t.get('action', '').upper() == 'BUY' and nb >= cost:
                    nb -= nb; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym} @{px}")
                elif t.get('action', '').upper() == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴卖出 {sym} @{px}")

            # 写入 Supabase
            supabase.table("drones").update({
                "balance": nb, "positions": np, "total_assets": round(nb + 1000, 2), # 此处可加市值计算
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] {(' | '.join(reports) if reports else '🟡观望')} | 🧠 {cmd.get('thought','')}"] + (d.get('logs') or []))[:20],
                "patrol_count": (int(d.get('patrol_count') or 0)) + 1,
                "memory": cmd.get('learning', d.get('memory'))
            }).eq("id", d["id"]).execute()
            
            status.write(f"🏁 **演化总耗时: {time.time()-total_start:.2f}s**")
            return True
        except Exception as e:
            status.write(f"❌ 崩溃: {str(e)}")
            return False

# --- 4. 界面渲染 ---
st.title("🐅 蜂群决策版 (对齐虎之眼核心)")
t1, t2, t3 = st.tabs(["🏆 工蜂档案", "👑 蜂后孵化", "⚙️ 系统管理"])

with t1:
    d_res = supabase.table("drones").select("*").order("created_at", desc=True).execute().data
    col_t, col_b = st.columns([4, 1])
    col_t.subheader("当前在线工蜂")
    if d_res and col_b.button("🔥 全力放飞全部", type="primary"):
        for d in d_res: evolve_drone_swarm(d)
        st.rerun()

    for d in (d_res or []):
        with st.expander(f"🐝 {d['name']} | 资产: ${d.get('total_assets', 0):,.2f}"):
            c1, c2, c3 = st.columns(3)
            c1.info(f"🎭 性格: {d.get('persona')}")
            c2.info(f"🧬 逻辑: {d.get('logic')}")
            c3.info(f"💾 记忆: {d.get('memory')}")
            if st.button(f"🚀 立即放飞", key=f"run_{d['id']}"):
                evolve_drone_swarm(d)
                st.rerun()
            st.metric("现金", f"${d['balance']:,.2f}")
            if d.get('positions'): st.json(d['positions'])
            for l in (d.get('logs') or [])[:5]: st.caption(l)

with t2:
    instr = st.text_area("孵化指令 (中文):")
    if st.button("开始孵化"):
        p = f"设计工蜂。返回纯JSON，内容中文。格式：{{'name':'','logic':'','persona':'','portfolio':['GLD','SLV']}}。指令：{instr}"
        r = gen_client.models.generate_content(model=MODEL_ID, contents=p)
        item = json.loads(r.text.replace("```json","").replace("```","").strip())
        item.update({"balance": 100000.0, "total_assets": 100000.0, "created_at": datetime.now(timezone.utc).isoformat(), "logs": ["已诞生"], "positions": {}})
        supabase.table("drones").insert(item).execute(); st.rerun()

with t3:
    if st.button("🔥 重置蜂巢"): supabase.table("drones").delete().neq("name", "RESERVED").execute(); st.rerun()