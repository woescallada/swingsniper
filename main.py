import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import requests
import json
from datetime import datetime
import time

# --- CONFIGURACIÓN VISUAL ---
st.set_page_config(page_title="Sniper Control Center", layout="wide", page_icon="🎛️")

st.markdown("""
    <style>
    .stDataFrame { font-size: 1.1rem; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; }
    .stButton button { width: 100%; border-radius: 8px; font-weight: bold; margin-bottom: 5px; }
    /* Estilos de botones */
    div[data-testid="column"]:nth-of-type(2) button:nth-of-type(1) { border: 2px solid #ff4b4b; } /* Hot Stocks */
    div[data-testid="column"]:nth-of-type(2) button:nth-of-type(2) { border: 2px solid #ffd700; } /* Penny Stocks */
    
    /* Cajas de info */
    .info-box { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #ff4b4b; color: black; }
    </style>
""", unsafe_allow_html=True)

# --- MEMORIA DE SESIÓN ---
if 'auto_candidates' not in st.session_state: st.session_state.auto_candidates = []
if 'last_update' not in st.session_state: st.session_state.last_update = None
if 'list_type' not in st.session_state: st.session_state.list_type = "Ninguna"
if 'data_source' not in st.session_state: st.session_state.data_source = ""
# Nueva variable para guardar los resultados finales y mostrarlos en grande
if 'final_results' not in st.session_state: st.session_state.final_results = None

# --- MOTOR DE DATOS ---

def get_backup_data(only_pennies=False):
    """PLAN B: Scrapea StockAnalysis.com si Yahoo falla."""
    candidates = []
    if only_pennies:
        urls = ["https://stockanalysis.com/markets/gainers/penny-stocks/", "https://stockanalysis.com/markets/active/penny-stocks/"]
    else:
        urls = ["https://stockanalysis.com/markets/gainers/", "https://stockanalysis.com/markets/active/"]
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                dfs = pd.read_html(r.text)
                if dfs:
                    df = dfs[0]
                    if 'Symbol' in df.columns: candidates.extend(df['Symbol'].tolist())
        except: continue  
    return list(set(candidates))

def get_market_data(only_pennies=False):
    """Intenta Yahoo -> Si falla, usa Respaldo."""
    candidates = []
    source_used = "Yahoo API"
    
    # INTENTO 1: YAHOO
    endpoints = [
        "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved/day_gainers?count=100&scrIds=day_gainers",
        "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved/most_actives?count=50&scrIds=most_actives"
    ]
    if only_pennies:
        endpoints.append("https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved/small_cap_gainers?count=100&scrIds=small_cap_gainers")

    headers = {'User-Agent': 'Mozilla/5.0', 'Origin': 'https://finance.yahoo.com'}
    
    try:
        for url in endpoints:
            r = requests.get(url, headers=headers, timeout=5)
            data = r.json()
            quotes = data['finance']['result'][0].get('quotes', [])
            for quote in quotes:
                sym = quote.get('symbol')
                price = quote.get('regularMarketPrice', 0)
                if sym and sym.isalpha():
                    if only_pennies and price > 20: continue 
                    candidates.append(sym)
    except: pass

    # INTENTO 2: RESPALDO
    if len(candidates) == 0:
        source_used = "StockAnalysis (Backup)"
        candidates.extend(get_backup_data(only_pennies))
    
    return list(set(candidates)), source_used

def get_guru_analysis(ticker):
    """Analiza una sola acción"""
    try:
        t = yf.Ticker(ticker)
        try: price = t.fast_info['last_price']
        except: 
            hist = t.history(period='1d')
            if not hist.empty: price = hist['Close'].iloc[-1]
            else: return None

        info = t.info
        df = t.history(period="6mo", interval="1d")
        if len(df) < 50: return None
        
        float_shares = info.get('floatShares', None)
        market_cap = info.get('marketCap', 0)
        if float_shares is None and price > 0: float_shares = market_cap / price 
            
        current_volume = df['Volume'].iloc[-1]
        avg_volume = df['Volume'].rolling(20).mean().iloc[-1]
        sma20, sma50, sma200 = df['Close'].rolling(20).mean().iloc[-1], df['Close'].rolling(50).mean().iloc[-1], (df['Close'].rolling(200).mean().iloc[-1] if len(df)>200 else 0)
        atr = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14).iloc[-1]
        day_range = df['High'].iloc[-1] - df['Low'].iloc[-1]
        close_pos = (df['Close'].iloc[-1] - df['Low'].iloc[-1]) / day_range if day_range > 0 else 0
        
        # SCORE SYSTEM
        score = 0
        if float_shares and float_shares < 10_000_000: score += 25
        elif float_shares and float_shares < 20_000_000: score += 15
        if float_shares and current_volume > float_shares: score += 25 
        rvol = current_volume / avg_volume if avg_volume > 0 else 0
        if rvol > 5.0: score += 20
        elif rvol > 3.0: score += 10
        if price > sma20 and price > sma50: score += 10
        if price > sma200: score += 5
        if close_pos > 0.75: score += 15
            
        return {
            "Ticker": ticker, "Precio": price, "Score": int(score),
            "Float (M)": float_shares / 1_000_000 if float_shares else 0,
            "RVOL": rvol, "Cierre %": close_pos * 100,
            "Stop Loss": max(price - (2.5 * atr), 0.01)
        }
    except: return None

def run_batch_analysis(ticker_list, origin_label, min_p, max_p, min_s):
    valid_data = []
    status_text = st.empty()
    bar = st.progress(0)
    total = len(ticker_list)
    
    for i, ticker in enumerate(ticker_list):
        bar.progress((i + 1) / total)
        status_text.text(f"Analizando {origin_label}: {ticker}...")
        data = get_guru_analysis(ticker)
        if data:
            if min_p <= data['Precio'] <= max_p and data['Score'] >= min_s:
                data['Origen'] = origin_label
                data['Riesgo %'] = ((data['Precio'] - data['Stop Loss']) / data['Precio']) * 100
                valid_data.append(data)
    
    bar.empty()
    status_text.empty()
    return valid_data

def style_dataframe(df):
    return df.style.applymap(lambda v: 'background-color: #00ff00; color: black; font-weight: bold' if v >= 80 else ('background-color: #ffff00; color: black' if v >= 60 else 'background-color: #ffcccc; color: black'), subset=['Score'])\
                   .applymap(lambda v: 'color: #800080; font-weight: bold' if v < 5 else ('color: #0000ff; font-weight: bold' if v < 15 else ''), subset=['Float (M)'])\
                   .applymap(lambda v: 'color: #006400; font-weight: bold' if v > 5 else '', subset=['RVOL'])\
                   .format({"Precio": "${:.2f}", "Float (M)": "{:.1f}M", "RVOL": "{:.1f}x", "Cierre %": "{:.0f}%", "Stop Loss": "${:.2f}", "Riesgo %": "{:.1f}%"})

# --- INTERFAZ ---
st.title("🎛️ Centro de Comando Sniper")

# --- GUÍA RÁPIDA (COLLAPSIBLE) ---
with st.expander("📘 GUÍA RÁPIDA: ¿Qué buscar en la tabla?", expanded=False):
    st.markdown("""
    <div class="info-box">
    <h4>🏆 El Setup Perfecto ("La Joya")</h4>
    <ul>
        <li><b>Score > 70:</b> La acción está fuerte técnicamente y tiene escasez de oferta.</li>
        <li><b>Float < 10M (Morado):</b> Hay pocas acciones disponibles. Si entra volumen, el precio vuela.</li>
        <li><b>RVOL > 3x:</b> Hoy hay 3 veces más gente comprando que un día normal. Algo pasa.</li>
        <li><b>Cierre % > 80%:</b> Los compradores mantuvieron el control hasta el final del día.</li>
    </ul>
    <hr>
    <h4>⚠️ Glosario Rápido</h4>
    <ul>
        <li><b>Float:</b> Acciones disponibles para el público. <i>Menos es mejor para volatilidad.</i></li>
        <li><b>RVOL (Relative Volume):</b> Volumen de hoy vs. Promedio. <i>Queremos > 2.0.</i></li>
        <li><b>Stop Loss:</b> Precio sugerido de salida si la cosa se pone fea (basado en ATR).</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

# SIDEBAR
st.sidebar.header("1. 📝 Tickers Manuales")
manual_txt = st.sidebar.text_area("Pega tus acciones aquí:", placeholder="TSLA AAPL AMC")
st.sidebar.markdown("---")
st.sidebar.header("2. ⚙️ Filtros")
min_price = st.sidebar.number_input("Min Precio", 0.1)
max_price = st.sidebar.number_input("Max Precio", 50.0)
min_score = st.sidebar.slider("Min Score", 0, 100, 50)

# PANEL DE CONTROL
c1, c2, c3 = st.columns(3)

# 1. MANUAL
with c1:
    st.subheader("1. Manual")
    if st.button("👤 Analizar Lista Manual"):
        if manual_txt.strip():
            raw_list = manual_txt.replace(',', ' ').split()
            clean_list = [x.strip().upper() for x in raw_list if x.strip()]
            with st.spinner(f"Analizando..."):
                results = run_batch_analysis(clean_list, "👤 Manual", min_price, max_price, min_score)
                if results:
                    st.session_state.final_results = pd.DataFrame(results).sort_values("Score", ascending=False)
                else:
                    st.warning("Nada pasó el filtro.")
                    st.session_state.final_results = None

# 2. IMPORTAR
with c2:
    st.subheader("2. Importar")
    if st.button("🔥 Todo (Hot)"):
        with st.spinner("Buscando..."):
            fetched, source = get_market_data(False)
            st.session_state.auto_candidates = fetched
            st.session_state.last_update = datetime.now().strftime("%H:%M")
            st.session_state.list_type = "Hot Stocks"
            st.session_state.data_source = source
            st.success(f"{len(fetched)} Acciones ({source})")
            
    if st.button("🪙 Solo Pennies"):
        with st.spinner("Buscando..."):
            fetched, source = get_market_data(True)
            st.session_state.auto_candidates = fetched
            st.session_state.last_update = datetime.now().strftime("%H:%M")
            st.session_state.list_type = "Pennies"
            st.session_state.data_source = source
            st.success(f"{len(fetched)} Pennies ({source})")

# 3. ANALIZAR
with c3:
    st.subheader("3. Ejecutar")
    can_analyze = len(st.session_state.auto_candidates) > 0
    if can_analyze:
        st.info(f"Lista: {st.session_state.list_type} ({len(st.session_state.auto_candidates)})")
    
    if st.button("⚡ Analizar Importadas", disabled=not can_analyze, type="primary"):
        results = run_batch_analysis(st.session_state.auto_candidates, "🤖 Auto", min_price, max_price, min_score)
        if results:
            st.session_state.final_results = pd.DataFrame(results).sort_values("Score", ascending=False)
        else:
            st.warning("Mercado difícil. Nada pasó tus filtros.")
            st.session_state.final_results = None

# --- ZONA DE RESULTADOS (FUERA DE LAS COLUMNAS PARA QUE SE VEA GRANDE) ---
st.markdown("---")

if st.session_state.final_results is not None:
    st.subheader("🎯 Tabla de Oportunidades")
    
    # Preparamos el dataframe para visualización
    df_show = st.session_state.final_results
    
    # Movemos columnas clave al principio
    cols = ['Ticker', 'Score', 'Precio', 'Float (M)', 'RVOL', 'Cierre %', 'Riesgo %', 'Stop Loss', 'Origen']
    df_show = df_show[cols]
    
    st.dataframe(
        style_dataframe(df_show),
        use_container_width=True, # ESTO HACE QUE OCUPE TODO EL ANCHO
        height=600
    )
else:
    st.info("👆 Usa los botones de arriba para generar una tabla de resultados.")
