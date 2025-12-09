import os
import json
import time
import logging
import traceback
from datetime import datetime, timedelta

import ccxt
import pandas as pd
import pandas_ta as ta
import requests
from ccxt.base.errors import ExchangeError

# ============================================================
# CONFIGURACIÓN DE LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURACIÓN DE ENTORNO Y CONSTANTES
# ============================================================
API_KEY = os.getenv("KRAKEN_API_KEY")
SECRET_KEY = os.getenv("KRAKEN_SECRET_KEY")

# Timeframe (Lectura de '1h' desde YAML)
TIMEFRAME = os.getenv("TIMEFRAME", "1h")

# Límite de Velas (Lectura de '50' desde YAML para optimizar MACD 12/26/9)
LIMIT = int(os.getenv("LIMIT", "50")) 

# Control de riesgo
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))
MAX_DRAWDOWN = float(os.getenv("MAX_DRAWDOWN", "0.05"))
COOLDOWN_HOURS = int(os.getenv("COOLDOWN_HOURS", "24"))

# PARÁMETROS DE TRAILING STOP LOSS (SL DINÁMICO)
TRAILING_PERCENT = float(os.getenv("TRAILING_PERCENT", "0.005")) # 0.5% margen de stop
MIN_PROFIT_TRIGGER = float(os.getenv("MIN_PROFIT_TRIGGER", "0.01")) # 1% de ganancia para activar trailing

# Telegram alerts via env vars
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")           # --> Grupo/Canal de Alertas (Público)
TELEGRAM_LOGS_CHAT_ID = os.getenv("TELEGRAM_LOGS_CHAT_ID") # --> Canal de Logs (Privado)

# Persistencia de estado
STATE_FILE = os.getenv("STATE_FILE", "bot_state.json")

# Símbolo por defecto
SYMBOL = os.getenv("SYMBOL", "BTC/USD")

# ============================================================
# INICIALIZACIÓN DE EXCHANGE CCXT
# ============================================================
if not API_KEY or API_KEY.strip() == "" or not SECRET_KEY or SECRET_KEY.strip() == "":
    logger.error("Las variables de entorno de Kraken no están configuradas.")
    raise SystemExit(1)

exchange = None
try:
    exchange = ccxt.kraken({
        "enableRateLimit": True,
        "apiKey": API_KEY,
        "secret": SECRET_KEY,
    })
    exchange.load_markets()
    logger.info("Exchange Kraken inicializado correctamente.")
except Exception as e:
    logger.critical("¡¡ERROR CRÍTICO AL INICIALIZAR CCXT!!")
    logger.critical(f"Razón: {e}")
    traceback.print_exc()
    raise SystemExit(1)

# ============================================================
# UTILIDADES DE ESTADO Y ALERTAS
# ============================================================
def load_state():
    """
    Carga el estado persistente del bot, incluyendo la posición y SL.
    """
    if not os.path.exists(STATE_FILE):
        return {
            "initial_balance": None,
            "cumulative_loss": 0.0,
            "shutdown_until": None,
            "position_open": False,
            "entry_price": 0.0,
            "last_stop_price": 0.0,
        }
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
            state.setdefault("position_open", False)
            state.setdefault("entry_price", 0.0)
            state.setdefault("last_stop_price", 0.0)
            return state
    except Exception as e:
        logger.error(f"No se pudo leer el archivo de estado: {e}")
        return {
            "initial_balance": None,
            "cumulative_loss": 0.0,
            "shutdown_until": None,
            "position_open": False,
            "entry_price": 0.0,
            "last_stop_price": 0.0,
        }

def save_state(state):
    """
    Guarda el estado del bot en disco.
    """
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"No se pudo guardar el archivo de estado: {e}")

def send_telegram_alert(message, chat_id=None):
    """
    Envía alertas a Telegram al chat_id especificado o al chat principal por defecto.
    """
    # Usa el ID de alertas principal por defecto
    target_chat_id = chat_id if chat_id else TELEGRAM_CHAT_ID 
    
    if not TELEGRAM_TOKEN or not target_chat_id:
        logger.debug(f"Telegram no configurado o target_chat_id ({target_chat_id}) es nulo. Omite alerta.")
        return
        
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        # Usamos Markdown para un formato profesional
        payload = {"chat_id": target_chat_id, "text": message, "parse_mode": "Markdown"} 
        resp = requests.post(url, data=payload, timeout=10)
        
        if resp.status_code != 200:
            logger.warning(f"Fallo enviando alerta a Telegram a {target_chat_id}: {resp.text}")
    except Exception as e:
        logger.warning(f"Excepción al enviar alerta a Telegram: {e}")

# ... (CONTROL DE RIESGO Y COOLDOWN) ...

def fetch_total_balance_in_usd():
    """ Obtiene el balance total en USD (o equivalente) usando CCXT. """
    try:
        bal = exchange.fetch_balance()
        total_usd = bal.get("total", {}).get("USD")
        if total_usd is None:
            fiat_total = 0.0
            for k, v in bal.get("total", {}).items():
                if k in ("USD", "USDT", "USDC"):
                    fiat_total += float(v or 0.0)
            total_usd = fiat_total
        if total_usd is None:
            logger.warning("No se pudo determinar el balance total en USD.")
            return 0.0
        return float(total_usd)
    except Exception as e:
        logger.error(f"Error obteniendo balance: {e}")
        return 0.0

def check_shutdown_and_drawdown(state):
    """ Verifica si el bot debe estar apagado por cooldown o si el drawdown supera el límite. """
    # Lógica de Cooldown
    if state.get("shutdown_until"):
        try:
            shut_dt = datetime.fromisoformat(state["shutdown_until"])
            if datetime.utcnow() < shut_dt:
                remaining = shut_dt - datetime.utcnow()
                logger.warning(f"Bot en cooldown. Restan {remaining}.")
                return True
            else:
                state["shutdown_until"] = None
                save_state(state)
        except Exception:
            state["shutdown_until"] = None
            save_state(state)

    # Chequear drawdown
    initial = state.get("initial_balance")
    if initial:
        cumulative_loss = float(state.get("cumulative_loss", 0.0))
        if cumulative_loss >= initial * MAX_DRAWDOWN:
            # Activa cooldown
            shut_until = datetime.utcnow() + timedelta(hours=COOLDOWN_HOURS)
            state["shutdown_until"] = shut_until.isoformat()
            save_state(state)
            msg = (f"⚠️ Drawdown ≥ {int(MAX_DRAWDOWN*100)}% alcanzado. "
                   f"Apagando bot por {COOLDOWN_HOURS}h. "
                   f"Pérdida acumulada: {cumulative_loss:.2f} USD.")
            logger.critical(msg)
            send_telegram_alert(msg)
            return True
    return False

def compute_position_size(balance_usd, price):
    """ Calcula el tamaño de posición con base en el 1% del balance. """
    if balance_usd <= 0 or price <= 0:
        return 0.0
    risk_amount = balance_usd * RISK_PER_TRADE
    qty = risk_amount / price
    return round(qty, 8)

# ============================================================
# DATOS Y INDICADORES
# ============================================================
def get_historical_data(symbol, timeframe, limit):
    """ Obtiene datos OHLCV desde Kraken con parámetros dinámicos. """
    try:
        klines = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        logger.info(f"Se obtuvieron {len(klines)} velas para {symbol} en {timeframe} con límite {limit}.")
        return klines
    except ExchangeError as e:
        logger.error("Error de la API de Kraken. Revisa llaves/permisos.")
        logger.error(f"Mensaje de Kraken: {e}")
        return None
    except Exception as e:
        logger.error("Error inesperado en get_historical_data.")
        logger.error(f"Razón: {e}")
        traceback.print_exc()
        return None

def calculate_macd(klines_data):
    """ Convierte OHLCV en DataFrame y calcula MACD (12, 26, 9). """
    if not klines_data or len(klines_data) == 0:
        logger.warning("No se recibieron velas para calcular MACD.")
        return None

    df = pd.DataFrame(klines_data, columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Timestamp"], unit="ms")
    df.ta.macd(close="Close", fast=12, slow=26, signal=9, append=True)
    logger.info("MACD calculado correctamente.")
    return df

def generate_signal(df):
    """ Determina BUY/SELL/HOLD analizando cruce de líneas en la última vela. """
    if df is None or len(df) == 0:
        logger.warning("No hay datos para generar señal.")
        return "NO DATA"

    last = df.iloc[-1]
    macd_line = last["MACD_12_26_9"]
    signal_line = last["MACDs_12_26_9"]
    
    if pd.isna(macd_line) or pd.isna(signal_line):
        return "HOLD"

    if macd_line > signal_line:
        return "BUY"
    elif macd_line < signal_line:
        return "SELL"
    else:
        return "HOLD"

# ============================================================
# TRAILING STOP LOSS (TL) Y MANEJO DE POSICIÓN
# ============================================================
def calculate_trailing_stop(state, current_price):
    """
    Calcula el nuevo nivel de Stop Loss (SL) dinámico.
    """
    if not state.get("position_open"):
        return state

    entry = state["entry_price"]
    last_stop = state["last_stop_price"]
    
    # Ganancia flotante actual
    profit_pct = (current_price - entry) / entry
    
    # 1. Calcular el Stop Loss Teórico (TL) basado en el margen de Trailing
    new_stop_price = current_price * (1 - TRAILING_PERCENT)
    
    # 2. Lógica del Activador: Si la ganancia no llega al trigger (ej: 1%), el SL NO se mueve
    if profit_pct < MIN_PROFIT_TRIGGER:
        # Chequeo de Stop Loss inicial fijo (-1% del precio de entrada)
        initial_stop_safety = entry * (1 - 0.01) 
        if current_price < initial_stop_safety:
            logger.critical(f"🛑 STOP LOSS INICIAL ACTIVADO. Precio {current_price:.2f} < SL {initial_stop_safety:.2f}")
            state["trigger_exit"] = "STOP LOSS"
        
        logger.info(f"Ganancia flotante ({profit_pct:.2%}) bajo el trigger ({MIN_PROFIT_TRIGGER:.2%}). SL no se mueve (último SL: {last_stop:.2f}).")
        return state

    # 3. Mover el Stop Loss solo si el nuevo TL es MAYOR que el último SL registrado
    if new_stop_price > last_stop:
        state["last_stop_price"] = new_stop_price
        
        msg = (f"📈 **TL ACTIVADO/ACTUALIZADO**\n"
               f"Ganancia Flotante: {profit_pct:.2%}\n"
               f"Nuevo Stop Loss: **{new_stop_price:.2f}**")
        
        send_telegram_alert(msg)
        logger.info(msg)
        
    return state

# ============================================================
# EJECUCIÓN DE ÓRDENES (STUB)
# ============================================================
def get_last_price(df):
    """ Obtiene el precio de cierre reciente del DataFrame ya cargado. """
    if df is None or len(df) == 0:
        logger.warning("No hay DataFrame para obtener el precio de cierre.")
        return 0.0
    return float(df.iloc[-1]["Close"])

def execute_trade_stub(signal, symbol, qty, price, execution_type="Signal"):
    """
    Stub de ejecución de órdenes con logs claros.
    """
    alert_emoji = "✅" if execution_type == "Signal" else "🛑"
    log_msg = (f"[{alert_emoji} PAPER] {execution_type}: Señal {signal} en {symbol} con cantidad {qty:.8f} @ {price:.2f}. (Ejecución deshabilitada)")
    logger.info(log_msg)
    
    # Enviar al canal de alertas principal (solo si es una acción de compra/venta)
    if signal in ("BUY", "SELL"):
        send_telegram_alert(f"{alert_emoji} **DECISIÓN:** {signal} {symbol} @ {price:.2f}. Razón: *{execution_type}*.")


def update_cumulative_loss_stub(state, symbol, signal):
    """
    Actualiza pérdida acumulada de forma simplificada en modo paper.
    Motivo de diseño:
    - Mantener un mecanismo de conteo de drawdown sin operar en real.
    Nota:
    - En producción, reemplazar por cálculo de PnL real (realizado y no realizado).
    """
    # Aquí solo dejamos la estructura y no alteramos loss para evitar falsas alarmas.
    pass

# ============================================================
# BLOQUE PRINCIPAL DE EJECUCIÓN
# ============================================================
if __name__ == "__main__":
    
    log_init_msg = f"Iniciando proceso para {SYMBOL} en timeframe {TIMEFRAME} con LIMIT={LIMIT}..."
    logger.info(log_init_msg)

    state = load_state()
    # 🚨 Log detallado al canal privado al inicio de cada ejecución
    send_telegram_alert(f"⚙️ **INICIO DE EJECUCIÓN (1h)**\n{log_init_msg}", chat_id=TELEGRAM_LOGS_CHAT_ID)


    if state["initial_balance"] is None:
        bal_usd = fetch_total_balance_in_usd()
        if bal_usd <= 0:
            logger.warning("Balance inicial no disponible. Se usará 0 para estado.")
            bal_usd = 0.0
        state["initial_balance"] = bal_usd
        save_state(state)
        logger.info(f"Balance inicial establecido: {bal_usd:.2f} USD")

    if check_shutdown_and_drawdown(state):
        logger.warning("Operación suspendida por políticas de riesgo/cooldown.")
        raise SystemExit(0)

    # 1. Obtener datos y calcular MACD
    klines_data = get_historical_data(SYMBOL, timeframe=TIMEFRAME, limit=LIMIT)
    if not klines_data or len(klines_data) == 0:
        logger.error("Fallo en la conexión o datos vacíos recibidos de Kraken.")
        raise SystemExit(1)

    df_macd = calculate_macd(klines_data)
    if df_macd is None:
        logger.error("No se pudo calcular MACD.")
        raise SystemExit(1)

    signal = generate_signal(df_macd)
    price = get_last_price(df_macd)
    bal_usd = fetch_total_balance_in_usd()
    qty = compute_position_size(bal_usd, price)
    
    # 2. Log detallado de la decisión (Canal privado)
    last = df_macd.iloc[-1]
    log_detail_msg = (
        f"📊 **LOG DETALLADO**\n"
        f"MACD: `{last['MACD_12_26_9']:.5f}`\n"
        f"Señal: `{last['MACDs_12_26_9']:.5f}`\n"
        f"Hist: `{last['MACDh_12_26_9']:.5f}`\n"
        f"Precio Actual: **{price:.2f}**\n"
        f"Decisión: **{signal}**\n"
        f"Posición Abierta: `{state['position_open']}`\n"
        f"Último SL: `{state['last_stop_price']:.2f}`"
    )
    send_telegram_alert(log_detail_msg, chat_id=TELEGRAM_LOGS_CHAT_ID)
    logger.info("Log detallado enviado al canal privado.")


    # 3. Manejo de Trailing Stop Loss y Cierre Forzado
    state["trigger_exit"] = None # Reset de trigger

    if state.get("position_open"):
        # Si hay posición abierta, calculamos el SL dinámico
        state = calculate_trailing_stop(state, price)
        
        # 🚨 Verificar si el precio actual ha cruzado el Trailing Stop Loss
        last_stop = state["last_stop_price"]
        if price < last_stop and last_stop > 0:
            logger.critical(f"🛑 TRAILING STOP ACTIVADO. Precio {price:.2f} < SL {last_stop:.2f}")
            state["trigger_exit"] = "TRAILING SL"

    # 4. Decisiones de Trading y Ejecución

    # Cierre Forzado (SL o Trailing SL)
    if state["trigger_exit"]:
        execute_trade_stub("SELL", SYMBOL, qty, price, execution_type=state["trigger_exit"])
        # En una ejecución real, aquí se calcularía la pérdida y se sumaría a cumulative_loss
        # update_cumulative_loss_stub(state, symbol, signal, is_loss=True)
        state["position_open"] = False
        state["entry_price"] = 0.0
        state["last_stop_price"] = 0.0
    
    # Apertura
    elif signal == "BUY" and not state.get("position_open"):
        # Apertura de posición
        execute_trade_stub(signal, SYMBOL, qty, price)
        state["position_open"] = True
        state["entry_price"] = price
        # SL inicial fijo (1% de riesgo inicial)
        state["last_stop_price"] = price * (1 - 0.01)
        
    # Cierre por Señal Contraria (SELL sin cierre forzado)
    elif signal == "SELL" and state.get("position_open"):
        # Cierre de posición por señal MACD
        execute_trade_stub("SELL", SYMBOL, qty, price, execution_type="Signal")
        # En una ejecución real, aquí se calcularía la ganancia/pérdida
        state["position_open"] = False
        state["entry_price"] = 0.0
        state["last_stop_price"] = 0.0
        
    # HOLD
    else:
        logger.info(f"Decisión de Trading: HOLD. Posición abierta: {state['position_open']}")


    # 5. Guardar Estado y Finalizar
    update_cumulative_loss_stub(state, SYMBOL, signal)
    save_state(state)

    if check_shutdown_and_drawdown(state):
        msg = f"Bot entra en cooldown por drawdown tras última decisión: {signal}"
        logger.warning(msg)
        send_telegram_alert(f"⚠️ {msg}")
    
    # Log de finalización
    send_telegram_alert(f"🏁 **FIN DE EJECUCIÓN**", chat_id=TELEGRAM_LOGS_CHAT_ID)

