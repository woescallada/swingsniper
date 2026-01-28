import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import time
from datetime import datetime

# --- CONFIGURACIÓN VISUAL ---
st.set_page_config(page_title="Penny Stock Sniper Color", layout="wide", page_icon="🚦")

# CSS para que los colores resalten más en modo oscuro/claro
st.markdown("""
    <style>
    .stDataFrame { font-size: 1.1rem; }
    </style>
""", unsafe_allow_html=True)

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = []

# --- MOTOR DE DATOS (IGUAL QUE LA VERSIÓN GURU) ---

@st.cache_data(ttl=600)
def get_raw_candidates():
    try:
        url = "https://finance.yahoo.com/gainers"
        tables = pd.read_html(url)
        return tables[0]['Symbol'].tolist()
    except:
        return []

def get_guru_analysis(ticker):
    try:
        t = yf.Ticker(ticker)
        info = t.info
        
        # Filtro de precio básico
        price = info.get('currentPrice', 0)
        if price == 0: 
            hist = t.history(period='1d')
            if not hist.empty: price = hist['Close'].iloc[-1]
            else: return None
                
        # Datos Históricos
        df = t.history(period="6mo", interval="1d")
        if len(df) < 50: return None
        
        # Variables
        float_shares = info.get('floatShares', None)
        market_cap = info.get('marketCap', 0)
        
        if float_shares is None and price > 0:
            float_shares = market_cap / price 
            
        current_volume = df['Volume'].iloc[-1]
        avg_volume = df['Volume'].rolling(20).mean().iloc[-1]
        
        # Indicadores
        sma20 = df['Close'].rolling(20).mean().iloc[-1]
        sma50 = df['Close'].rolling(50).mean().iloc[-1]
        sma200 = df['Close'].rolling(200).mean().iloc[-1] if len(df) > 200 else 0
        rsi = ta.momentum.rsi(df['Close'], window=14).iloc[-1]
        atr = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14).iloc[-1]
        
        # Posición de cierre
        day_range = df['High'].iloc[-1] - df['Low'].iloc[-1]
        close_pos = (df['Close'].iloc[-1] - df['Low'].iloc[-1]) / day_range if day_range > 0 else 0
        
        # --- SCORING ---
        score = 0
        
        # 1. Supply Shock
        if float_shares and float_shares < 10_000_000: score += 25
        elif float_shares and float_shares < 20_000_000: score += 15
            
        # 2. Volume Blast
        if float_shares and current_volume > float_shares: score += 25 # Rotación total
            
        # 3. RVOL
        rvol = current_volume / avg_volume if avg_volume > 0 else 0
        if rvol > 5.0: score += 20
        elif rvol > 3.0: score += 10
        
        # 4. Tendencia
        if price > sma20 and price > sma50: score += 10
        if price > sma200: score += 5
        
        # 5. Cierre Fuerte
        if close_pos > 0.75: score += 15
            
        return {
            "Ticker": ticker,
            "Precio": price,
            "Score": int(score), # Entero para facilitar colores
            "Float (M)": float_shares / 1_000_000 if float_shares else 0,
            "RVOL": rvol,
            "RSI": rsi,
            "Cierre %": close_pos * 100,
            "ATR": atr,
            "Stop Loss": max(price - (2.5 * atr), 0.01) # Evitar stop negativo
        }

    except:
        return None

# --- SIDEBAR ---
st.sidebar.title("🚦 Filtros Visuales")
min_score = st.sidebar.slider("Filtrar Basura (Score Min)", 0, 100, 60)
st.sidebar.info("Este panel usa colores para priorizar tu atención.")

# --- LÓGICA DE COLORES (LA CLAVE) ---
def highlight_rows(val):
    """Pinta el fondo del Score según calidad"""
    if val >= 85:
        return 'background-color: #00ff00; color: black; font-weight: bold' # VERDE FLÚOR
    elif val >= 70:
        return 'background-color: #90ee90; color: black' # VERDE CLARO
    elif val >= 50:
        return 'background-color: #ffff00; color: black' # AMARILLO
    else:
        return 'background-color: #ffcccb; color: black' # ROJO CLARO

def highlight_float(val):
    """Resalta floats peligrosamente bajos"""
    if val < 5:
        return 'color: #800080; font-weight: bold' # MORADO (Micro Float)
    elif val < 15:
        return 'color: #0000ff; font-weight: bold' # AZUL (Low Float)
    return ''

def highlight_rvol(val):
    """Resalta volumen masivo"""
    if val > 5:
        return 'color: green; font-weight: bold'
    return ''

# --- UI PRINCIPAL ---
st.title("🚦 Scanner Visual de Penny Stocks")
st.write("Objetivo: Busca las filas **VERDES** con Floats **MORADOS**.")

if st.button("🔎 ESCANEAR MERCADO", type="primary"):
    
    with st.spinner("Analizando Oferta y Demanda..."):
        candidates = get_raw_candidates()
        
        if not candidates:
            st.error("Error conectando con Yahoo Finance.")
        else:
            data_list = []
            progress = st.progress(0)
            
            for i, ticker in enumerate(candidates):
                progress.progress((i+1)/len(candidates))
                res = get_guru_analysis(ticker)
                
                if res and res['Score'] >= min_score:
                    # Cálculo de riesgo visual
                    risk_pct = ((res['Precio'] - res['Stop Loss']) / res['Precio']) * 100
                    res['Riesgo %'] = risk_pct
                    data_list.append(res)
            
            progress.empty()
            
            if data_list:
                df = pd.DataFrame(data_list).sort_values(by="Score", ascending=False)
                
                st.success(f"✅ {len(df)} Oportunidades encontradas.")
                
                # --- APLICACIÓN DE ESTILOS DE COLOR ---
                st.dataframe(
                    df.style
                    .applymap(highlight_rows, subset=['Score'])
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
                    height=600
                )
                
                # Leyenda Rápida
                st.markdown("---")
                c1, c2, c3 = st.columns(3)
                c1.markdown("🟢 **Score > 85:** Compra Fuerte (Alta Probabilidad)")
                c2.markdown("🟣 **Float < 5M:** Dinamita (Puede subir 50% hoy)")
                c3.markdown("⚡ **RVOL > 5x:** Volumen Institucional")
                
            else:
                st.warning("Ninguna acción superó el filtro de calidad.")
