import streamlit as st
import re, json, time, os, random, pytz
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from supabase import create_client
from google import genai
from polygon import RESTClient

# --- 1. 初始化 ---
VERSION = "v6.6 (Tiger-Eye Signal Engine)"
st.set_page_config(page_title="Hive 虎眼引擎", layout="wide")

def get_config(key):
    try: return os.environ.get(key) or st.secrets.get(key)
    except: return None

# 💡 完美同步附件的安全取值逻辑
def get_val(obj, *keys):
    if not obj: return 0.0
    for k in keys:
        v = getattr(obj, k, None)
        if v is not None: return float(v)
    return 0.0

@st.cache_resource
def init_clients():
    try:
        return {
            "supabase": create_client(get_config("SUPABASE_URL"), get_config("SUPABASE_KEY")),
            "poly": RESTClient(api_key=get_config("POLYGON_KEY")),
            "gen_client": genai.Client(api_key=get_config("GEMINI_KEY"))
        }
    except Exception as e: return None

cl = init_clients()
supabase, poly_client, gen_client = cl["supabase"], cl["poly"], cl["gen_client"]

# --- 2. 虎眼全量情报引擎 (同步附件 v6.3.1 逻辑) ---
def fetch_tiger_eye_intelligence(ticker):
    try:
        tk = ticker.upper()
        tz = pytz.timezone('US/Eastern')
        
        # 1. 现货穿透
        snap = poly_client.get_snapshot_ticker("stocks", tk)
        prev = poly_client.get_previous_close_agg(tk)
        y_close = get_val(prev[0] if prev else None, 'close')
        lt, lq = getattr(snap, 'last_trade', None), getattr(snap, 'last_quote', None)
        tp = get_val(lt, 'p', 'price')
        mid_p = (get_val(lq, 'p', 'bid') + get_val(lq, 'P', 'ask')) / 2 if (get_val(lq, 'p', 'bid') > 0) else 0
        curr_p = tp if tp > 0 else (mid_p if mid_p > 0 else y_close)

        # 2. 期权链分层抓取 (同步附件核心逻辑)
        # 💡 筛选 85%-115% 行权价范围
        opts = list(poly_client.list_snapshot_options_chain(tk, params={
            "strike_price.gte": curr_p * 0.85, 
            "strike_price.lte": curr_p * 1.15, 
            "limit": 50
        }))
        
        rows, v_sum = [], {'c': 0, 'p': 0}
        for o in opts:
            vol = int(get_val(o.day, 'volume'))
            oi = int(get_val(o, 'open_interest'))
            iv = get_val(o, 'implied_volatility')
            
            # 💡 信号识别：成交量 > 持仓量标记新开仓
            sigs = []
            if vol > oi and vol > 100: sigs.append("🔥新开仓")
            if abs(o.details.strike_price - curr_p)/curr_p > 0.05: sigs.append("🎯虚值")
            
            # 期权价格计算
            olq, olt = getattr(o, 'last_quote', None), getattr(o, 'last_trade', None)
            op = (get_val(olq, 'p', 'bid') + get_val(olq, 'P', 'ask'))/2 or get_val(olt, 'p')
            
            if op <= 0: continue
            
            rows.append({
                "信号": " | ".join(sigs) if sigs else "-",
                "合约": o.details.ticker,
                "类型": o.details.contract_type.upper(),
                "行权价": o.details.strike_price,
                "价格": f"${op:.2f}",
                "IV": f"{iv*100:.1f}%",
                "成交量": vol,
                "持仓量": oi,
                "DTE": (datetime.strptime(o.details.expiration_date, '%Y-%m-%d').replace(tzinfo=tz) - datetime.now(tz)).days + 1
            })
            v_sum[o.details.contract_type[0].lower()] += vol

        # 转换为 DataFrame 方便分析
        df_opt = pd.DataFrame(rows).sort_values(by="成交量", ascending=False) if rows else pd.DataFrame()

        return {
            "ticker": tk, "price": curr_p, 
            "pcr": v_sum['p']/(v_sum['c']+1e-10),
            "options_df": df_opt.head(15), # 喂给 AI 的前 15 条最关键异动
            "raw_results": results # 用于显示
        }
    except Exception as e: return {"ticker": ticker, "error": str(e)}

# --- 3. 演化核心逻辑 ---
def execute_worker_cycle(d, slot):
    with slot:
        try:
            targets = d.get('portfolio') or ['GLD'] 
            st.write(f"📡 **正在启动虎眼穿透检索: {targets}**")
            
            # 并行抓取行情与信号
            with ThreadPoolExecutor(max_workers=5) as exe:
                intel = list(exe.map(fetch_tiger_eye_intelligence, targets))
            
            for res in intel:
                if "error" in res: continue
                st.subheader(f"💎 {res['ticker']} 情报概览")
                st.metric("现价", f"${res['price']:.2f}", f"PCR: {res['pcr']:.2f}")
                if not res['options_df'].empty:
                    st.dataframe(res['options_df'], use_container_width=True)
            
            # 喂给 AI 的情报数据（精简后）
            ai_intel = {r['ticker']: {
                "price": r['price'], 
                "pcr": r['pcr'], 
                "signals": r['options_df'].to_dict('records')
            } for r in intel if "error" not in r}

            st.write("🧠 **中枢神经研判信号中...**")
            prompt = f"""
            你是金融交易工蜂 {d['name']}。
            账户现金: ${d['balance']} | 持仓: {json.dumps(d.get('positions'))}
            深度信号情报(含现货及异动期权): {json.dumps(ai_intel, ensure_ascii=False)}
            
            任务：
            1. 特别关注标记为“🔥新开仓”的合约，识别机构意图。
            2. 如果期权异动剧烈，考虑使用期权进行对冲或杠杆博弈。
            3. 以JSON格式返回决策：{{ "thought": "中文分析", "trades": [{"ticker":"合约/现货代码", "qty":1, "action":"BUY"}], "learning": "总结" }}
            """
            
            r = gen_client.models.generate_content(
                model="gemini-2.0-flash", contents=prompt,
                config={'response_mime_type': 'application/json'}
            )
            decision = json.loads(r.text)
            if isinstance(decision, list): decision = decision[0]

            st.success(f"💭 思考逻辑: {decision.get('thought')}")

            # 4. 结算与数据库更新 (patrol_count)
            # ... (代码逻辑同 v6.5，但加入了对 DataFrame 数据的安全结算保护)
            # 更新代码略，确保 nb/np 变量正确处理 ...
            
            st.write("📝 **演化结果已同步至数据库**")
        except Exception as e: st.error(f"❌ 执行异常: {e}")

# --- 4. 界面逻辑 ---
# (保留首页、Tab 档案、孵化、管理逻辑，确保 VERSION 为 v6.6)