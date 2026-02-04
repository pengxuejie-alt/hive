# --- 修正后的演化执行逻辑 (v5.1) ---
def execute_worker_cycle(d, slot):
    with slot:
        try:
            st.write("📡 **正在穿透行情...**")
            targets = d.get('portfolio', ['GLD'])
            with ThreadPoolExecutor(max_workers=5) as exe:
                results = list(exe.map(fetch_nectar, targets))
            nectar_data = {r['代码']: r for r in results if r['现价'] > 0}
            
            st.info(f"📊 实时行情: {json.dumps(nectar_data, ensure_ascii=False)}")

            prompt = f"你是工蜂{d['name']}。基因:{d['persona']}。现金:{d['balance']}。持仓:{json.dumps(d.get('positions'))}。行情:{json.dumps(nectar_data)}。返回决策JSON。"
            decision = safe_brain_decision(prompt)

            nb, np, reports = float(d['balance']), (d.get('positions', {}) or {}).copy(), []
            for t in decision.get('trades', []):
                sym, qty, act = t.get('ticker', '').upper(), t.get('qty', 0), t.get('action', '').upper()
                px = fetch_nectar(sym)['现价']
                if px <= 0: continue
                # 💡 期权乘数为 100
                multiplier = 100 if ("O:" in sym or len(sym) > 6) else 1
                cost = qty * px * multiplier
                
                if act == 'BUY' and nb >= cost:
                    nb -= cost; np[sym] = np.get(sym, 0) + qty
                    reports.append(f"🟢买入 {sym}@{px}")
                elif act == 'SELL' and np.get(sym, 0) >= qty:
                    nb += cost; np[sym] -= qty
                    if np[sym] <= 0: del np[sym]
                    reports.append(f"🔴卖出 {sym}@{px}")

            # 💡 核心计算：持仓市值 (Market Value)
            mv = 0.0
            for s, q in np.items():
                current_px = fetch_nectar(s)['现价']
                m = 100 if ("O:" in s or len(s) > 6) else 1
                mv += q * current_px * m
            
            total = round(nb + mv, 2)
            
            # 💡 更新数据：将市值信息存入 logs 或 total_assets
            update_data = {
                "balance": nb,
                "positions": np,
                "total_assets": total,
                "logs": ([f"[{datetime.now().strftime('%H:%M:%S')}] 市值:${mv:,.2f} | {(' | '.join(reports) if reports else '观望')}"] + (d.get('logs') or []))[:10],
                "patrol_count": (d.get('patrol_count', 0) + 1),
                "fitness_score": round((total / (d.get('initial_balance', 100000.0) or 100000.0)) * 100, 2)
            }
            
            supabase.table("drones").update(update_data).eq("id", d["id"]).execute()
            st.success(f"✅ 演化完成。当前市值: ${mv:,.2f}")
            time.sleep(1); st.rerun()
        except Exception as e:
            st.error(f"❌ 运行崩溃: {e}")

# --- TAB 0 档案面板增强显示 ---
# 在 Expander 标题中直接展示三项数据
# label = f"🐝 {d['name']} | 总资产: ${d['total_assets']:,.2f} | 现金: ${d['balance']:,.2f} | 持仓市值: ${round(d['total_assets']-d['balance'], 2):,.2f}"