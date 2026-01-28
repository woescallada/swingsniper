import streamlit as st
import yfinance as yf
import pandas as pd
import ta
import time
import requests
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

# --- MOTOR DE DATOS (CON BYPASS ANTI-BOT) ---

@st.cache_data(ttl=600)
def get_raw_candidates():
    """Obtiene tickers simulando ser un navegador real para evitar bloqueo 403"""
    try:
        url = "https://finance.yahoo.com/gainers"
        
        # DISFRAZ: Headers de Chrome
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers)
        
        # Si falla la petición HTTP
        if response.status_code != 200:
            st.warning(f"Yahoo respondió con código {response.status_code}. Usando lista de emergencia.")
            return ["MULN", "GME", "AMC", "MARA", "RIOT", "SOFI", "PLTR", "NVDA", "AMD", "TSLA"]
            
        tables = pd.read_html(response.text)
        return tables[0]['Symbol'].tolist()
        
    except Exception as e:
        st.error(f"Error de conexión: {e}. Usando lista de respaldo.")
        return ["MULN", "GME", "AMC", "MARA", "RIOT", "SOFI", "PLTR", "NVDA", "AMD", "TSLA"]

def get_guru_analysis(ticker):
    """Análisis Técnico + Fundamental (Float)"""
    try:
        t = yf.Ticker(ticker)
        # Info fundamental (Float)
        info = t.info
        
        # Filtro de precio básico (Evitar errores si no hay precio)
        price = info.get('currentPrice', 0)
        if price == 0: 
            hist_now = t.history(period='1d')
            if not hist_now.empty: price = hist_now['Close'].iloc[-1]
            else: return None
                
        # Descargar historial para técnico (6 meses)
        df = t.history(period="6mo", interval="1d")
        if len(df) < 50: return None
        
        # --- VARIABLES CLAVE ---
        float_shares = info.get('floatShares', None)
        market_cap = info.get('marketCap', 0)
        
        # Estimación de Float si Yahoo devuelve None
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
        
        # Posición de cierre (0 a 1)
        day_range = df['High'].iloc[-1] - df['Low'].iloc[-1]
        close_pos = (df['Close'].iloc[-1] - df['Low'].iloc[-1]) / day_range if day_range > 0 else 0
        
        # --- SISTEMA DE PUNTUACIÓN (GURU SCORE) ---
        score = 0
        
        # 1. Supply Shock (Escasez)
        if float_shares and float_shares < 10_000_000: score += 25
        elif float_shares and float_shares < 20_000_000: score += 15
            
        # 2. Volume Blast (Demanda Extrema)
        if float_shares and current_volume > float_shares: score += 25 
            
        # 3. RVOL (Momentum)
        rvol = current_volume / avg_volume if avg_volume > 0 else 0
        if rvol > 5.0: score += 20
        elif rvol > 3.0: score += 10
        
        # 4. Estructura de Tendencia
        if price > sma20 and price > sma50: score += 10
        if price > sma200: score += 5
        
        # 5. Cierre Fuerte (Para Swing)
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
            "Stop Loss": max(price - (2.5 * atr), 0.01) # Stop técnico amplio
        }

    except:
        return None

# --- SIDEBAR (PANEL LATERAL) ---
st.sidebar.title("🦈 Filtros Guru")
st.sidebar.markdown("**Configuración de Escáner**")

min_price = st.sidebar.number_input("Precio Mín ($)", value=0.5)
max_price = st.sidebar.number_input("Precio Máx ($)", value=25.0)
min_score = st.sidebar.slider("Score Calidad Mínimo", 0, 100, 60, help="Menos de 60 suele ser ruido.")

st.sidebar.markdown("---")
st.sidebar.info("💡 **Semáforo:**\n\n🟢 **Verde:** Compra Fuerte\n🟣 **Texto Morado:** Float < 10M (Explosivo)")

# --- ESTILOS DE COLOR (FUNCIONES PANDAS) ---
def highlight_score(val):
    if val >= 80: return 'background-color: #00ff00; color: black; font-weight: bold' # Verde Fósforo
    elif val >= 60: return 'background-color: #ffff00; color: black' # Amarillo
    return 'background-color: #ffcccc; color: black' # Rojo claro

def highlight_float(val):
    if val < 5: return 'color: #800080; font-weight: bold' # Morado oscuro
    if val < 15: return 'color: #0000ff; font-weight: bold' # Azul fuerte
    return ''

def highlight_rvol(val):
    if val > 5: return 'color: #006400; font-weight: bold' # Verde oscuro
    return ''

# --- INTERFAZ PRINCIPAL ---
st.title("🚦 Supply Shock Scanner")
st.write("Detectando desequilibrios de Oferta y Demanda en tiempo real.")

if st.button("🔎 EJECUTAR ANÁLISIS", type="primary"):
    
    with st.spinner("Bypassing Yahoo Security & Analizando Floats..."):
        candidates = get_raw_candidates()
        
        # Progreso
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        valid_data = []
        
        for i, ticker in enumerate(candidates):
            progress_bar.progress((i + 1) / len(candidates))
            status_text.text(f"Analizando estructura de: {ticker}")
            
            data = get_guru_analysis(ticker)
            
            if data:
                # FILTROS USUARIO
                if min_price <= data['Precio'] <= max_price:
                    if data['Score'] >= min_score:
                        # Calcular Riesgo Visual
                        riesgo = ((data['Precio'] - data['Stop Loss']) / data['Precio']) * 100
                        data['Riesgo %'] = riesgo
                        valid_data.append(data)
        
        progress_bar.empty()
        status_text.empty()
        
        if valid_data:
            df = pd.DataFrame(valid_data).sort_values(by="Score", ascending=False)
            
            st.success(f"✅ Se encontraron {len(df)} oportunidades calificadas.")
            
            # MOSTRAR TABLA COLOREADA
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
                height=600
            )
            
            # BOTÓN DESCARGA
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Descargar CSV para Excel",
                csv,
                f"guru_scan_{datetime.now().strftime('%H%M')}.csv",
                "text/csv"
            )
        else:
            st.warning("📉 Ninguna acción superó tus filtros estrictos. El mercado hoy está débil o demasiado caro.")
