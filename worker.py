import os, json, pytz
import google.generativeai as genai
from polygon import RESTClient
from supabase import create_client
from datetime import datetime

# --- 初始化 ---
client_poly = RESTClient(api_key=os.environ.get("POLYGON_KEY"))
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
genai.configure(api_key=os.environ.get("GEMINI_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

def patrol_and_evolve():
    # ... (市场状态检查逻辑保持不变) ...
    drones = supabase.table("drones").select("*").execute().data
    for d in drones:
        try:
            # 协议约束：确保代码必须能被 API 识别
            prompt = f"""你是专业交易员兵蜂 {d['name']}。
            基因逻辑: {d['logic']} | 往期记忆: {d.get('memory')}
            现金: ${d['balance']} | 持仓: {d.get('positions')}
            
            【Ticker 协议约束】:
            - 股票/ETF: 使用代码 (如 'FCX', 'TSLA')。
            - 期权: 必须使用 Polygon 标准格式 'O:SYMBOLYYMMDD[C/P]行权价'。
              (例如: 'O:FCX260116C00050000')。
            - 严禁在 symbol 字段写入策略名称。
            
            请针对当前行情决策并深度复盘。
            返回纯JSON: {{"action":"BUY/SELL/HOLD", "symbol":"...", "qty":0, "price":0, "reason":"...", "learning":"..."}}
            """
            
            res = model.generate_content(prompt).text.strip()
            cmd = json.loads(res.replace("```json", "").replace("```", "").strip())
            
            # --- 账本更新逻辑保持不变 ---
            # 迭代记忆：存入复盘心得
            update['memory'] = f"最新记录：{cmd['learning']}"
            # 保存到 Supabase
            supabase.table("drones").update(update).eq("id", d["id"]).execute()
        except Exception as e: print(f"错误: {e}")

if __name__ == "__main__":
    patrol_and_evolve()