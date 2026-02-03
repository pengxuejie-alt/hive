import streamlit as st
import pandas as pd
from supabase import create_client
import pytz, json
from datetime import datetime
from polygon import RESTClient

# --- 初始化 ---
supabase = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
poly_client = RESTClient(api_key=st.secrets["POLYGON_KEY"])

def get_total_valuation(positions):
    mv = 0.0
    details = []
    for k, v in (positions or {}).items():
        try:
            # 简化的估值逻辑
            p = poly_client.get_last_trade(k).price if k.startswith("O:") else poly_client.get_snapshot_ticker("stocks", k).last_trade.p
            val = float(v) * float(p) * (100 if k.startswith("O:") else 1)
            mv += val
            details.append({"代码": k, "持仓": v, "市值": f"${val:,.2f}"})
        except: pass
    return mv, details

st.title("🐝 Hive 蜂巢：实时演化看板")

res = supabase.table("drones").select("*").execute()
if res.data:
    for d in res.data:
        # 核心：资产加总逻辑
        cash = float(d.get('balance', 10000.0))
        mkt_val, pos_details = get_total_valuation(d.get('positions'))
        total_assets = cash + mkt_val
        
        with st.expander(f"🐝 {d['name']} | 资产总值: ${total_assets:,.2f} | 现金: ${cash:,.2f}"):
            # 持仓明细
            if pos_details:
                st.write("**📦 当前持仓:**")
                st.table(pd.DataFrame(pos_details))
            
            # --- 核心：流水日志展示 ---
            st.write("---")
            st.subheader("📜 巡检流水记录 (时间 | 方向 | 思考)")
            logs = d.get('logs', [])
            if logs:
                for log in logs:
                    # 根据方向上色或加粗（通过 caption 或 markdown）
                    st.markdown(f"`{log}`")
            else:
                st.write("尚无流水记录")