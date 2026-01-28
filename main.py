import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import requests
import json
from datetime import datetime

# --- CONFIGURACIÓN VISUAL ---
st.set_page_config(page_title="Penny Stock Sniper Guru", layout="wide", page_icon="🦈")

# CSS para forzar colores oscuros/claros legibles y tablas grandes
st.markdown("""
    <style>
    .stDataFrame { font-size: 1.1rem; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; }
    </style>
""", unsafe_allow_html=True)

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = []

# --- MOTOR DE DATOS (CONEXIÓN API DIRECTA) ---

@st.cache_data(ttl=300)
def get_raw_candidates():
    """Obtiene Top Gainers y Activas desde la API JSON de Yahoo (Anti-Bloqueo)"""
    candidates = []
    
    # Endpoints directos de la API (sin HTML scraping)
    endpoints = [
        "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved/day_gainers?count=100&scrIds=day_gainers",
        "https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved/most_actives?count=50&scrIds=most_actives"
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Origin': 'https://finance.yahoo.com'
    }

    for url in endpoints:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            data = response.json()
            
            if 'finance' in data and 'result' in data['finance']:
                quotes = data['finance']['result'][0].get('quotes', [])
                for quote in quotes:
                    symbol = quote.get('symbol')
                    if symbol and symbol.isalpha(): 
                        candidates.append(symbol)
        except:
            continue

    return list(set(candidates))

def get_guru_analysis(ticker):
    """Análisis Técnico + Fundamental (Float)"""
    try:
        t = yf.Ticker(ticker)
        info = t.info
        
        # 1. Obtener Precio Actual con seguridad
        price = info.get('currentPrice', 0)
        if price == 0: 
            # Intentar backup con fast_info o history
            try: price = t.fast_info['last_price']
            except: 
                hist = t.history(period='1d')
                if not hist.empty: price = hist['Close'].iloc[-1]
                else: return None
        
        # 2. Descargar Historial (6 meses)
        df = t.history(period="6mo", interval="1d")
        if len(df) < 50: return None
        
        # --- VARIABLES CLAVE ---
        float_shares = info.get('floatShares', None)
        market_cap = info.get('marketCap', 0)
        
        if float_shares is None and price > 0:
            float_shares = market_cap / price 
            
        current_volume = df['Volume'].iloc[-1]
        avg_volume = df['Volume'].rolling(20).mean().iloc[-1]
        
        # --- INDICADORES ---
        sma20 = df['Close'].rolling(20).mean().iloc[-1]
        sma50 = df['Close'].rolling(50).mean().iloc[-1]
        sma200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) > 200 else 0
        rsi = ta.momentum.rsi(df['Close'], window=14).iloc[-1]
        atr = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14).iloc[-1]
        
        day_range = df['High'].iloc[-1] - df['Low'].iloc[-1]
        close_pos = (df['Close'].iloc[-1] - df['Low'].iloc[-1]) / day_range if day_range > 0 else 0
        
        # --- GURU SCORE (Algoritmo de Puntuación) ---
        score = 0
        
        # A. Supply Shock
        if float_shares and float_shares < 10_000_000: score += 25
        elif float_shares and float_shares < 20_000_000: score += 15
            
        # B. Volume Blast
        if float_shares and current_volume > float_shares: score += 25 
            
        # C. RVOL
        rvol = current_volume / avg_volume if avg_volume > 0 else 0
        if rvol > 5.0: score += 20
        elif rvol > 3.0: score += 10
        
        # D. Tendencia
        if price > sma20 and price > sma50: score += 10
        if price > sma200: score += 5
        
        # E. Price Action
        if close_pos > 0.75: score += 15
            
        return {
            "Ticker": ticker,
            "Precio": price,
            "Score": int(score),
            "Float (M)": float_shares / 1_000_000 if float_shares else 0,
            "RVOL": rvol,
            "RSI": rsi,
            "Cierre %": close_pos * 100,
            "ATR": atr,
            "Stop Loss": max(price - (2.5 * atr), 0.01)
        }

    except:
        return None

# --- SIDEBAR (PANEL LATERAL) ---
st.sidebar.title("🦈 Filtros Guru")

# 1. INPUT MANUAL DE TICKERS
st.sidebar.markdown("### ✍️ Añadir Mis Tickers")
manual_input = st.sidebar.text_area(
    "Pégalos aquí (separados por coma o espacio):", 
    placeholder="Ej: TSLA, AAPL, AMC, GME"
)

st.sidebar.markdown("---")
st.sidebar.markdown("**Configuración de Escáner**")

# Filtros
min_price = st.sidebar.number_input("Precio Mín ($)", value=0.5)
max_price = st.sidebar.number_input("Precio Máx ($)", value=50.0) # Subido a 50 por defecto
min_score = st.sidebar.slider("Score Calidad Mínimo", 0, 100, 50)

st.sidebar.info("💡 **Nota:** Tus tickers manuales también deben cumplir los filtros de precio para aparecer.")

# --- ESTILOS DE COLOR ---
def highlight_score(val):
    if val >= 80: return 'background-color: #00ff00; color: black; font-weight: bold' 
    elif val >= 60: return 'background-color: #ffff00; color: black'
    return 'background-color: #ffcccc; color: black'

def highlight_float(val):
    if val < 5: return 'color: #800080; font-weight: bold'
    if val < 15: return 'color: #0000ff; font-weight: bold'
    return ''

def highlight_rvol(val):
    if val > 5: return 'color: #006400; font-weight: bold'
    return ''

# --- INTERFAZ PRINCIPAL ---
st.title("🚦 Supply Shock Scanner + Manual Watchlist")

if st.button("🔎 EJECUTAR ANÁLISIS", type="primary"):
    
    with st.spinner("Conectando con mercados y fusionando listas..."):
        
        # 1. Obtener candidatos automáticos
        market_candidates = get_raw_candidates()
        
        # 2. Procesar candidatos manuales
        manual_candidates = []
        if manual_input:
            # Limpieza: quitar comas, convertir a mayúsculas y quitar espacios
            raw_list = manual_input.replace(',', ' ').split()
            manual_candidates = [x.strip().upper() for x in raw_list if x.strip()]
        
        # 3. Fusión y limpieza de duplicados
        all_tickers = list(set(market_candidates + manual_candidates))
        
        status_text = st.empty()
        progress_bar = st.progress(0)
        valid_data = []
        
        # 4. Bucle de análisis
        for i, ticker in enumerate(all_tickers):
            progress_bar.progress((i + 1) / len(all_tickers))
            status_text.text(f"Analizando: {ticker}")
            
            data = get_guru_analysis(ticker)
            
            if data:
                # APLICAR FILTROS
                if min_price <= data['Precio'] <= max_price:
                    if data['Score'] >= min_score:
                        
                        # Marca visual si es manual
                        if ticker in manual_candidates:
                            data['Origen'] = "👤 Manual"
                        else:
                            data['Origen'] = "🤖 Auto"
                            
                        # Riesgo
                        riesgo = ((data['Precio'] - data['Stop Loss']) / data['Precio']) * 100
                        data['Riesgo %'] = riesgo
                        valid_data.append(data)
        
        progress_bar.empty()
        status_text.empty()
        
        if valid_data:
            # Ordenar: Primero por Score
            df = pd.DataFrame(valid_data).sort_values(by="Score", ascending=False)
            
            # Reordenar columnas para poner Origen al principio
            cols = ['Ticker', 'Origen', 'Score', 'Precio', 'Float (M)', 'RVOL', 'RSI', 'Cierre %', 'Riesgo %', 'Stop Loss']
            df = df[cols]
            
            st.success(f"✅ Análisis completado: {len(df)} acciones encontradas.")
            
            st.dataframe(
                df.style
                .applymap(highlight_score, subset=['Score'])
                .applymap(highlight_float, subset=['Float (M)'])
                .applymap(highlight_rvol, subset=['RVOL'])
                .format({
                    "Precio": "${:.2f}",
                    "Float (M)": "{:.1f}M",
                    "RVOL": "{:.1f}x",
                    "RSI": "{:.0f}",
                    "Cierre %": "{:.0f}%",
                    "Stop Loss": "${:.2f}",
                    "Riesgo %": "{:.1f}%"
                }),
                use_container_width=True,
                height=700
            )
        else:
            st.warning("📉 Ninguna acción (ni automática ni manual) pasó tus filtros.")
