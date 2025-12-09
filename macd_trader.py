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
from ccxt.base.errors import ExchangeError, NetworkError # Importar NetworkError

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
# CONFIGURACIÓN DE ENTORNO Y CONSTANTES (MODO REAL)
# ============================================================
API_KEY = os.getenv("KRAKEN_API_KEY")
SECRET_KEY = os.getenv("KRAKEN_SECRET_KEY")

# MODO DE EJECUCIÓN: Leer de Secrets (True = Paper, False = Real)
PAPER_TRADING_MODE = os.getenv("PAPER_TRADING_MODE", "True").lower() == "true" 

# PARÁMETROS ESPECÍFICOS PARA ADA/USD
SYMBOL = os.getenv("SYMBOL", "ADA/USD")
MICRO_QTY = float(os.getenv("MICRO_QTY", "10")) # Cantidad base para pruebas reales (ej: 10 ADA)

# Timeframe y Límite de Velas
TIMEFRAME = os.getenv("TIMEFRAME", "1h")
LIMIT = int(os.getenv("LIMIT", "50")) 

# Control de riesgo
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))
MAX_DRAWDOWN = float(os.getenv("MAX_DRAWDOWN", "0.05"))
COOLDOWN_HOURS = int(os.getenv("COOLDOWN_HOURS", "24"))

# PARÁMETROS DE TRAILING STOP LOSS (SL DINÁMICO)
TRAILING_PERCENT = float(os.getenv("TRAILING_PERCENT", "0.005"))
MIN_PROFIT_TRIGGER = float(os.getenv("MIN_PROFIT_TRIGGER", "0.01"))

# Telegram alerts via env vars
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_LOGS_CHAT_ID = os.getenv("TELEGRAM_LOGS_CHAT_ID")

# Persistencia de estado
STATE_FILE = os.getenv("STATE_FILE", "bot_state.json")

# ============================================================
# INICIALIZACIÓN DE EXCHANGE CCXT
# ============================================================
# ... (Bloque de inicialización de CCXT sin cambios) ...

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
# ... (load_state, save_state, send_telegram_alert sin cambios) ...

def load_state():
    """ Carga el estado persistente del bot. """
    # ... (código load_state) ...
    if not os.path.exists(STATE_FILE):
        return {
            "initial_balance": None,
            "cumulative_loss": 0.0,
            "shutdown_until": None,
            "position_open": False,
            "entry_price": 0.0,
            "last_stop_price": 0.0,
            "position_qty": 0.0, # Añadido para el modo real
        }
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
            state.setdefault("position_open", False)
            state.setdefault("entry_price", 0.0)
            state.setdefault("last_stop_price", 0.0)
            state.setdefault("position_qty", 0.0) # Añadido para el modo real
            return state
    except Exception as e:
        # ... (código de manejo de error) ...
        logger.error(f"No se pudo leer el archivo de estado: {e}")
        return {
            "initial_balance": None,
            "cumulative_loss": 0.0,
            "shutdown_until": None,
            "position_open": False,
            "entry_price": 0.0,
            "last_stop_price": 0.0,
            "position_qty": 0.0,
        }

def save_state(state):
    # ... (código save_state sin cambios) ...
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"No se pudo guardar el archivo de estado: {e}")

def send_telegram_alert(message, chat_id=None):
    # ... (código send_telegram_alert sin cambios) ...
    target_chat_id = chat_id if chat_id else TELEGRAM_CHAT_ID 
    
    if not TELEGRAM_TOKEN or not target_chat_id:
        logger.debug(f"Telegram no configurado o target_chat_id ({target_chat_id}) es nulo. Omite alerta.")
        return
        
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": target_chat_id, "text": message, "parse_mode": "Markdown"} 
        resp = requests.post(url, data=payload, timeout=10)
        
        if resp.status_code != 200:
            logger.warning(f"Fallo enviando alerta a Telegram a {target_chat_id}: {resp.text}")
    except Exception as e:
        logger.warning(f"Excepción al enviar alerta a Telegram: {e}")

# ============================================================
# CONTROL DE RIESGO Y COOLDOWN (PnL REAL Y BALANCE SIMULADO)
# ============================================================
def fetch_total_balance_in_usd():
    # ... (código fetch_total_balance_in_usd sin cambios, usa simulado) ...
    SIMULATED_BALANCE = 5000.00 

    try:
        bal = exchange.fetch_balance()
        total_usd = bal.get("total", {}).get("USD")
        
        if total_usd is None or float(total_usd) <= 0:
            logger.warning(f"Usando balance simulado de {SIMULATED_BALANCE:.2f} USD para cálculo de riesgo.")
            return SIMULATED_BALANCE
            
        return float(total_usd)
        
    except Exception as e:
        logger.error(f"Error obteniendo balance, usando simulado: {e}")
        return SIMULATED_BALANCE

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
    if initial and initial > 0: # Solo chequear si el balance inicial es > 0
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
    """ 
    Calcula el tamaño de posición basado en riesgo o usa la cantidad mínima (MICRO_QTY) 
    para la prueba real.
    """
    if balance_usd <= 0 or price <= 0:
        return 0.0
        
    # Si estamos en modo REAL (micro-capital), usamos la cantidad mínima fija.
    if not PAPER_TRADING_MODE:
        logger.info(f"Usando MICRO_QTY ({MICRO_QTY}) para ejecución REAL en {SYMBOL}.")
        return MICRO_QTY
        
    # Lógica de Paper Trading (cálculo de riesgo):
    risk_amount = balance_usd * RISK_PER_TRADE
    qty = risk_amount / price
    return round(qty, 8)
    
def update_pnl_and_drawdown(state, entry_price, exit_price, side):
    """
    Calcula el PnL real (simulado con el precio de cierre) y actualiza el drawdown.
    """
    if side != "SELL":
        return state

    qty = state.get("position_qty", MICRO_QTY) # Usamos la cantidad de la posición guardada
    
    # Cálculo simple de PnL (sin comisiones de Kraken, por ahora)
    pnl_usd = (exit_price - entry_price) * qty
    logger.info(f"PNL Real (bruto): {pnl_usd:.4f} USD")
    
    if pnl_usd < 0:
        state["cumulative_loss"] += abs(pnl_usd)
        msg = (f"📉 **PÉRDIDA REGISTRADA**\n"
               f"PNL: {pnl_usd:.4f} USD\n"
               f"Pérdida Acumulada: {state['cumulative_loss']:.2f} USD")
        send_telegram_alert(msg)
    else:
        msg = f"📈 **GANANCIA REGISTRADA**\nPNL: +{pnl_usd:.4f} USD"
        send_telegram_alert(msg)

    return state

# ============================================================
# DATOS Y INDICADORES (Sin cambios)
# ... (get_historical_data, calculate_macd, generate_signal, calculate_trailing_stop) ...
# ============================================================

def get_historical_data(symbol, timeframe, limit):
    # ... (código get_historical_data sin cambios) ...
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
    # ... (código calculate_macd sin cambios) ...
    if not klines_data or len(klines_data) == 0:
        logger.warning("No se recibieron velas para calcular MACD.")
        return None

    df = pd.DataFrame(klines_data, columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Timestamp"], unit="ms")
    df.ta.macd(close="Close", fast=12, slow=26, signal=9, append=True)
    logger.info("MACD calculado correctamente.")
    return df

def generate_signal(df):
    # ... (código generate_signal sin cambios) ...
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

def calculate_trailing_stop(state, current_price):
    # ... (código calculate_trailing_stop sin cambios) ...
    if not state.get("position_open"):
        return state

    entry = state["entry_price"]
    last_stop = state["last_stop_price"]
    
    profit_pct = (current_price - entry) / entry
    new_stop_price = current_price * (1 - TRAILING_PERCENT)
    
    if profit_pct < MIN_PROFIT_TRIGGER:
        initial_stop_safety = entry * (1 - 0.01) 
        if current_price < initial_stop_safety:
            logger.critical(f"🛑 STOP LOSS INICIAL ACTIVADO. Precio {current_price:.2f} < SL {initial_stop_safety:.2f}")
            state["trigger_exit"] = "STOP LOSS"
        
        logger.info(f"Ganancia flotante ({profit_pct:.2%}) bajo el trigger ({MIN_PROFIT_TRIGGER:.2%}). SL no se mueve (último SL: {last_stop:.2f}).")
        return state

    if new_stop_price > last_stop:
        state["last_stop_price"] = new_stop_price
        
        msg = (f"📈 **TL ACTIVADO/ACTUALIZADO**\n"
               f"Ganancia Flotante: {profit_pct:.2%}\n"
               f"Nuevo Stop Loss: **{new_stop_price:.4f}**")
        
        send_telegram_alert(msg)
        logger.info(msg)
        
    return state
    
# ============================================================
# EJECUCIÓN DE ÓRDENES (REAL O STUB)
# ============================================================
def get_last_price(df):
    """ Obtiene el precio de cierre reciente del DataFrame ya cargado. """
    if df is None or len(df) == 0:
        logger.warning("No hay DataFrame para obtener el precio de cierre.")
        return 0.0
    return float(df.iloc[-1]["Close"])

def execute_real_trade(signal, symbol, qty, price, execution_type="Signal"):
    """
    Ejecuta una orden de trading real o simula si PAPER_TRADING_MODE es True.
    Retorna el precio de ejecución real.
    """
    alert_emoji = "✅" if execution_type in ("Signal", "BUY") else "🛑"
    side = "buy" if signal == "BUY" else "sell"
    
    # ------------------------------------
    # MODO PAPER TRADING (STUB)
    # ------------------------------------
    if PAPER_TRADING_MODE:
        log_msg = f"[{alert_emoji} PAPER] {execution_type}: Señal {signal} en {symbol} con cantidad {qty:.8f} @ {price:.4f}."
        logger.info(log_msg)
        if signal in ("BUY", "SELL"):
            send_telegram_alert(f"{alert_emoji} **DECISIÓN (PAPER):** {signal} {symbol} @ {price:.4f}. Razón: *{execution_type}*.", chat_id=TELEGRAM_CHAT_ID)
        return price # En paper trading, el precio de ejecución es el precio actual.
        
    # ------------------------------------
    # MODO EJECUCIÓN REAL (CCXT)
    # ------------------------------------
    try:
        # Usamos orden de mercado para ejecución rápida
        order = exchange.create_order(
            symbol=symbol,
            type="market",
            side=side,
            amount=qty,
        )
        # Extraer precio de ejecución (si no está disponible inmediatamente, usamos el precio de mercado)
        exec_price = float(order.get("price", price))
        
        log_msg = f"[{alert_emoji} REAL] 💰 ORDEN {signal} EXITOSA. Qty: {qty:.8f} @ {exec_price:.4f}. ID: {order['id']}"
        logger.critical(log_msg)
        send_telegram_alert(f"{alert_emoji} **ORDEN REAL {signal} EJECUTADA**\nPrecio: **{exec_price:.4f}** | Qty: `{qty:.8f}`", chat_id=TELEGRAM_CHAT_ID)
        return exec_price
        
    except (ExchangeError, NetworkError) as e:
        error_msg = f"🚨 ERROR CRÍTICO CCXT ({execution_type} {signal}): {e}"
        logger.critical(error_msg)
        send_telegram_alert(f"🚨 **FALLO CRÍTICO DE ORDEN**\n{error_msg}", chat_id=TELEGRAM_CHAT_ID)
        return 0.0 # Indicar fallo
    except Exception as e:
        error_msg = f"🚨 ERROR INESPERADO AL EJECUTAR ORDEN: {e}"
        logger.critical(error_msg)
        send_telegram_alert(f"🚨 **FALLO INESPERADO**\n{error_msg}", chat_id=TELEGRAM_CHAT_ID)
        return 0.0

# ============================================================
# BLOQUE PRINCIPAL DE EJECUCIÓN
# ============================================================
if __name__ == "__main__":
    
    # ... (código de inicialización y logs) ...
    log_init_msg = f"Iniciando proceso para {SYMBOL} en timeframe {TIMEFRAME} con LIMIT={LIMIT}. Modo REAL: {not PAPER_TRADING_MODE}."
    logger.info(log_init_msg)

    state = load_state()
    send_telegram_alert(f"⚙️ **INICIO DE EJECUCIÓN (1h)**\n{log_init_msg}", chat_id=TELEGRAM_LOGS_CHAT_ID)

    # ... (código de balance inicial y drawdown check) ...
    if state["initial_balance"] is None:
        bal_usd = fetch_total_balance_in_usd() 
        if bal_usd <= 0:
            logger.error("Error: Balance inicial no puede ser 0 después del simulado.")
            raise SystemExit(1) 
        state["initial_balance"] = bal_usd
        save_state(state)
        logger.info(f"Balance inicial establecido: {bal_usd:.2f} USD")

    if check_shutdown_and_drawdown(state):
        logger.warning("Operación suspendida por políticas de riesgo/cooldown.")
        raise SystemExit(0)

    # ... (Obtener datos, calcular MACD y señal) ...
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
    qty = compute_position_size(bal_usd, price) # Calcula MICRO_QTY si PAPER_TRADING_MODE=False
    
    # 2. Log detallado de la decisión (Canal privado)
    last = df_macd.iloc[-1]
    log_detail_msg = (
        f"📊 **LOG DETALLADO**\n"
        f"MACD: `{last['MACD_12_26_9']:.5f}`\n"
        f"Señal: `{last['MACDs_12_26_9']:.5f}`\n"
        f"Precio Actual: **{price:.4f} {SYMBOL.split('/')[1]}**\n"
        f"Decisión: **{signal}** | QTY: **{qty:.4f}**\n"
        f"Posición Abierta: `{state['position_open']}` | Entrada: `{state['entry_price']:.4f}`\n"
        f"Último SL: `{state['last_stop_price']:.4f}`"
    )
    send_telegram_alert(log_detail_msg, chat_id=TELEGRAM_LOGS_CHAT_ID)
    logger.info("Log detallado enviado al canal privado.")


    # 3. Manejo de Trailing Stop Loss y Cierre Forzado
    state["trigger_exit"] = None

    if state.get("position_open"):
        state = calculate_trailing_stop(state, price)
        
        last_stop = state["last_stop_price"]
        if price < last_stop and last_stop > 0:
            logger.critical(f"🛑 TRAILING STOP ACTIVADO. Precio {price:.4f} < SL {last_stop:.4f}")
            state["trigger_exit"] = "TRAILING SL"

    # 4. Decisiones de Trading y Ejecución

    execute_trade = execute_real_trade

    # Cierre Forzado (SL o Trailing SL)
    if state["trigger_exit"]:
        # Se usa la cantidad previamente guardada en el estado
        exit_price = execute_trade("SELL", SYMBOL, state.get("position_qty", qty), price, execution_type=state["trigger_exit"])
        if exit_price > 0:
            state = update_pnl_and_drawdown(state, state["entry_price"], exit_price, "SELL")
            state["position_open"] = False
            state["entry_price"] = 0.0
            state["last_stop_price"] = 0.0
            state["position_qty"] = 0.0
    
    # Apertura
    elif signal == "BUY" and not state.get("position_open"):
        exec_price = execute_trade(signal, SYMBOL, qty, price)
        if exec_price > 0: 
            state["position_open"] = True
            state["entry_price"] = exec_price
            state["last_stop_price"] = exec_price * (1 - 0.01)
            state["position_qty"] = qty # ¡Guardar la cantidad operada (MICRO_QTY)!
        
    # Cierre por Señal Contraria (SELL sin cierre forzado)
    elif signal == "SELL" and state.get("position_open"):
        # Se usa la cantidad previamente guardada en el estado
        exit_price = execute_trade("SELL", SYMBOL, state.get("position_qty", qty), price, execution_type="Signal")
        if exit_price > 0: 
            state = update_pnl_and_drawdown(state, state["entry_price"], exit_price, "SELL")
            state["position_open"] = False
            state["entry_price"] = 0.0
            state["last_stop_price"] = 0.0
            state["position_qty"] = 0.0
        
    # HOLD
    else:
        logger.info(f"Decisión de Trading: HOLD. Posición abierta: {state['position_open']}")


    # 5. Guardar Estado y Finalizar
    save_state(state)

    if check_shutdown_and_drawdown(state):
        msg = f"Bot entra en cooldown por drawdown tras última decisión: {signal}"
        logger.warning(msg)
        send_telegram_alert(f"⚠️ {msg}")
    
    send_telegram_alert(f"🏁 **FIN DE EJECUCIÓN**", chat_id=TELEGRAM_LOGS_CHAT_ID)
