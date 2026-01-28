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
    </style>
""", unsafe_allow_html=True)

# --- MEMORIA DE SESIÓN ---
if 'auto_candidates' not in st.session_state:
    st.session_state.auto_candidates = []
if 'last_update' not in st.session_state:
    st.session_state.last_update = None
if 'list_type' not in st.session_state:
    st.session_state.list_type = "Ninguna"
if 'data_source' not in st.session_state:
    st.session_state.data_source = ""

# --- MOTOR DE DATOS (MÚLTIPLES FUENTES) ---

def get_backup_data(only_pennies=False):
    """
    PLAN B: Scrapea StockAnalysis.com si Yahoo falla.
    Es más robusto y tiene listas dedicadas.
    """
    candidates = []
    
    # URLs de StockAnalysis (Fuente Respaldo)
    if only_pennies:
        urls = [
            "https://stockanalysis.com/markets/gainers/penny-stocks/",
            "https://stockanalysis.com/markets/active/penny-stocks/"
        ]
    else:
        urls = [
            "https://stockanalysis.com/markets/gainers/",
            "https://stockanalysis.com/markets/active/"
        ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    for url in urls:
        try:
            # Usamos requests para descargar el HTML simulando ser un navegador real
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                # Pandas lee las tablas HTML automáticamente
                dfs = pd.read_html(r.text)
                if dfs:
                    df = dfs[0] # La primera tabla suele ser la buena
                    # Buscamos la columna de símbolos (Symbol)
                    if 'Symbol' in df.columns:
                        symbols = df['Symbol'].tolist()
                        candidates.extend(symbols)
        except Exception as e:
            print(f"Error backup {url}: {e}")
            continue
            
    return list(set(candidates))

def get_market_data(only_pennies=False):
    """
    Lógica inteligente: Intenta Yahoo -> Si falla, usa Respaldo.
    """
    candidates = []
    source_used = "Yahoo API"
    
    # --- INTENTO 1: YAHOO ---
    endpoints = [
        "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved/day_gainers?count=100&scrIds=day_gainers",
        "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved/most_actives?count=50&scrIds=most_actives"
    ]
    if only_pennies:
        endpoints.append("https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved/small_cap_gainers?count=100&scrIds=small_cap_gainers")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Origin': 'https://finance.yahoo.com'
    }

    progress = st.progress(0)
    
    # Intentamos Yahoo
    try:
        for i, url in enumerate(endpoints):
            r = requests.get(url, headers=headers, timeout=5)
            data = r.json()
            quotes = data['finance']['result'][0].get('quotes', [])
            for quote in quotes:
                sym = quote.get('symbol')
                price = quote.get('regularMarketPrice', 0)
                if sym and sym.isalpha():
                    if only_pennies and price > 20: continue # Filtro extra seguridad
                    candidates.append(sym)
            progress.progress((i + 1) / (len(endpoints) * 2)) # Barra al 50%
    except:
        pass

    # --- INTENTO 2: RESPALDO (Si Yahoo dio 0 resultados) ---
    if len(candidates) == 0:
        source_used = "StockAnalysis (Backup)"
        st.toast("⚠️ Yahoo bloqueado. Activando Plan B (StockAnalysis)...", icon="🔄")
        time.sleep(1) # Pequeña pausa
        
        backup_candidates = get_backup_data(only_pennies)
        candidates.extend(backup_candidates)
        
    progress.progress(1.0)
    progress.empty()
    
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
        
        sma20 = df['Close'].rolling(20).mean().iloc[-1]
        sma50 = df['Close'].rolling(50).mean().iloc[-1]
        sma200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) > 200 else 0
        atr = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14).iloc[-1]
        
        day_range = df['High'].iloc[-1] - df['Low'].iloc[-1]
        close_pos = (df['Close'].iloc[-1] - df['Low'].iloc[-1]) / day_range if day_range > 0 else 0
        
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
            "Ticker": ticker,
            "Precio": price,
            "Score": int(score),
            "Float (M)": float_shares / 1_000_000 if float_shares else 0,
            "RVOL": rvol,
            "Cierre %": close_pos * 100,
            "Stop Loss": max(price - (2.5 * atr), 0.01)
        }
    except:
        return None

def run_batch_analysis(ticker_list, origin_label, min_p, max_p, min_s):
    valid_data = []
    status_text = st.empty()
    bar = st.progress(0)
    
    total = len(ticker_list)
    for i, ticker in enumerate(ticker_list):
        bar.progress((i + 1) / total)
        status_text.text(f"Analizando {origin_label} ({i}/{total}): {ticker}...")
        
        data = get_guru_analysis(ticker)
        
        if data:
            if min_p <= data['Precio'] <= max_p and data['Score'] >= min_s:
                data['Origen'] = origin_label
                riesgo = ((data['Precio'] - data['Stop Loss']) / data['Precio']) * 100
                data['Riesgo %'] = riesgo
                valid_data.append(data)
    
    bar.empty()
    status_text.empty()
    return valid_data

def style_dataframe(df):
    return df.style.applymap(lambda v: 'background-color: #00ff00; color: black; font-weight: bold' if v >= 80 else ('background-color: #ffff00; color: black' if v >= 60 else 'background-color: #ffcccc; color: black'), subset=['Score'])\
                   .applymap(lambda v: 'color: #800080; font-weight: bold' if v < 5 else ('color: #0000ff; font-weight: bold' if v < 15 else ''), subset=['Float (M)'])\
                   .format({"Precio": "${:.2f}", "Float (M)": "{:.1f}M", "RVOL": "{:.1f}x", "Cierre %": "{:.0f}%", "Stop Loss": "${:.2f}", "Riesgo %": "{:.1f}%"})

# --- INTERFAZ ---
st.title("🎛️ Centro de Comando Sniper")

# SIDEBAR
st.sidebar.header("1. 📝 Tickers Manuales")
manual_txt = st.sidebar.text_area("Pega tus acciones aquí:", placeholder="TSLA AAPL AMC")
st.sidebar.markdown("---")
st.sidebar.header("2. ⚙️ Filtros Finales")
min_price = st.sidebar.number_input("Min Precio", 0.1)
max_price = st.sidebar.number_input("Max Precio", 50.0)
min_score = st.sidebar.slider("Min Score", 0, 100, 50)

# PANEL DE CONTROL (3 COLUMNAS)
c1, c2, c3 = st.columns(3)

# --- COLUMNA 1: MANUAL ---
with c1:
    st.subheader("1. Manual")
    if st.button("👤 Analizar Lista Manual"):
        if manual_txt.strip():
            raw_list = manual_txt.replace(',', ' ').split()
            clean_list = [x.strip().upper() for x in raw_list if x.strip()]
            with st.spinner(f"Analizando {len(clean_list)} manuales..."):
                results = run_batch_analysis(clean_list, "👤 Manual", min_price, max_price, min_score)
            if results:
                st.success(f"✅ {len(results)} Resultados")
                st.dataframe(style_dataframe(pd.DataFrame(results).sort_values("Score", ascending=False)), use_container_width=True)
            else: st.warning("Nada pasó el filtro.")
        else: st.error("Lista vacía.")

# --- COLUMNA 2: IMPORTAR (FUENTE INTELIGENTE) ---
with c2:
    st.subheader("2. Importar Mercado")
    
    # Botón A: Mercado General
    if st.button("🔥 Importar TODO (Hot Stocks)"):
        with st.spinner("Buscando en Yahoo + Backups..."):
            fetched, source = get_market_data(only_pennies=False)
            st.session_state.auto_candidates = fetched
            st.session_state.last_update = datetime.now().strftime("%H:%M:%S")
            st.session_state.list_type = "Hot Stocks Global"
            st.session_state.data_source = source
        if len(fetched) > 0:
            st.success(f"📥 {len(fetched)} Acciones (Fuente: {source})")
        else:
            st.error("❌ Fallaron todas las fuentes de datos.")
    
    # Botón B: Solo Pennies
    if st.button("🪙 Importar SOLO Pennies"):
        with st.spinner("Buscando Pennies en Yahoo + Backups..."):
            fetched, source = get_market_data(only_pennies=True)
            st.session_state.auto_candidates = fetched
            st.session_state.last_update = datetime.now().strftime("%H:%M:%S")
            st.session_state.list_type = "Pennies (<$15)"
            st.session_state.data_source = source
        if len(fetched) > 0:
            st.success(f"📥 {len(fetched)} Pennies (Fuente: {source})")
        else:
            st.error("❌ Fallaron todas las fuentes de datos.")

# --- COLUMNA 3: ANALIZAR IMPORTADAS ---
with c3:
    st.subheader("3. Ejecutar Sniper")
    can_analyze = len(st.session_state.auto_candidates) > 0
    
    # Mostrar info detallada
    if can_analyze:
        st.info(f"**Lista:** {st.session_state.list_type}\n**Fuente:** {st.session_state.data_source}\n**Hora:** {st.session_state.last_update}")
    else:
        st.warning("⚠️ Memoria vacía. Importa primero.")

    if st.button("⚡ Analizar Importadas", disabled=not can_analyze, type="primary"):
        candidates = st.session_state.auto_candidates
        results = run_batch_analysis(candidates, "🤖 Auto", min_price, max_price, min_score)
        
        if results:
            st.success(f"✅ {len(results)} Oportunidades")
            df = pd.DataFrame(results).sort_values(by="Score", ascending=False)
            st.dataframe(style_dataframe(df), use_container_width=True, height=600)
        else:
            st.warning("Mercado difícil. Ninguna acción pasó tus filtros.")
