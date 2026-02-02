def is_market_open():
    """判断当前美东时间是否在盘中"""
    et_tz = pytz.timezone('US/Eastern')
    now = datetime.now(et_tz)
    if now.weekday() >= 5: return False
    # 09:30 - 16:00
    start = now.replace(hour=9, minute=30, second=0)
    end = now.replace(hour=16, minute=0, second=0)
    return start <= now <= end

def patrol_and_evolve():
    is_open = is_market_open()
    drones = supabase.table("drones").select("*").execute().data
    
    for d in drones:
        try:
            m_data = get_market_data(d)
            
            # 无论开不开盘，都进行分析和学习，但非盘中禁止交易动作
            action_restriction = "" if is_open else "【当前非交易时段，禁止执行 BUY/SELL，仅允许 HOLD】"
            
            prompt = f"""
            你是兵蜂 {d['name']}。{action_restriction}
            行情：{m_data} | 余额：{d['balance']}
            输出JSON：{{"action":"BUY/SELL/HOLD","symbol":"...","qty":0,"price":0,"reason":"...","learning":"..."}}
            """
            # ... (后续执行逻辑)
            # 如果 !is_open 且 action != 'HOLD'，强制设为 HOLD 并记录“盘外尝试违规交易”