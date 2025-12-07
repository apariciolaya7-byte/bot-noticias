import os
import pandas as pd
import pandas_ta as ta
import ccxt
import traceback
import logging
from ccxt.base.errors import ExchangeError

# ============================================================
# CONFIGURACIÓN DE LOGGING
# ============================================================
# Se configura el logger global con formato estándar:
# [timestamp] [nivel] mensaje
logging.basicConfig(
    level=logging.INFO,  # Nivel mínimo de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURACIÓN DE KRAKEN
# ============================================================
API_KEY = os.getenv('KRAKEN_API_KEY')
SECRET_KEY = os.getenv('KRAKEN_SECRET_KEY')

if not API_KEY or API_KEY.strip() == "" or not SECRET_KEY or SECRET_KEY.strip() == "":
    logger.error("Las variables de entorno de Kraken no están configuradas.")
    exit(1)

exchange = None

try:
    exchange = ccxt.kraken({
        'enableRateLimit': True,
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
    })
    exchange.load_markets()
    logger.info("Exchange Kraken inicializado correctamente.")

except Exception as e:
    logger.critical("¡¡ERROR CRÍTICO AL INICIALIZAR CCXT!!")
    logger.critical(f"Razón: {e}")
    traceback.print_exc()
    exit(1)


# ============================================================
# FUNCIÓN: get_historical_data
# ============================================================
def get_historical_data(symbol, timeframe, limit):
    """
    Obtiene datos de velas (candlesticks) de Kraken usando CCXT.
    Maneja errores específicos de la API y errores generales.
    """
    global exchange

    try:
        klines = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        logger.info(f"Se obtuvieron {len(klines)} velas para {symbol} en {timeframe}.")
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


# ============================================================
# FUNCIÓN: calculate_macd
# ============================================================
def calculate_macd(klines_data):
    """
    Convierte los datos OHLCV en un DataFrame y calcula el indicador MACD.
    Devuelve un DataFrame con columnas: MACD_12_26_9, MACDs_12_26_9, MACDh_12_26_9.
    """
    if not klines_data or len(klines_data) == 0:
        logger.warning("No se recibieron datos de velas para calcular MACD.")
        return None

    df = pd.DataFrame(klines_data, columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"])
    df["Date"] = pd.to_datetime(df["Timestamp"], unit="ms")

    df.ta.macd(close="Close", fast=12, slow=26, signal=9, append=True)
    logger.info("MACD calculado correctamente sobre el DataFrame.")

    return df


# ============================================================
# FUNCIÓN: generate_signal
# ============================================================
def generate_signal(df):
    """
    Analiza la última fila del DataFrame con MACD y determina la acción de trading.
    Retorna: 'BUY', 'SELL' o 'HOLD'.
    """
    if df is None or len(df) == 0:
        logger.warning("No hay datos disponibles para generar señal.")
        return "NO DATA"

    last_row = df.iloc[-1]

    macd_line = last_row["MACD_12_26_9"]
    signal_line = last_row["MACDs_12_26_9"]
    hist_line = last_row["MACDh_12_26_9"]

    logger.debug(f"Última vela → MACD: {macd_line:.5f}, Señal: {signal_line:.5f}, Histograma: {hist_line:.5f}")

    if macd_line > signal_line:
        return "BUY"
    elif macd_line < signal_line:
        return "SELL"
    else:
        return "HOLD"


# ============================================================
# BLOQUE PRINCIPAL DE EJECUCIÓN
# ============================================================
if __name__ == '__main__':

    SYMBOL = 'BTC/USD'
    TIMEFRAME = '5m'
    LIMIT = 100

    logger.info(f"Iniciando proceso para {SYMBOL} en timeframe {TIMEFRAME}...")

    klines_data = get_historical_data(SYMBOL, TIMEFRAME, LIMIT)

    if klines_data and len(klines_data) > 0:
        df_macd = calculate_macd(klines_data)

        if df_macd is not None:
            signal = generate_signal(df_macd)
            logger.info(f"Decisión de Trading para {SYMBOL}: {signal}")
        else:
            logger.error("No se pudo calcular MACD.")
    else:
        logger.error("Fallo en la conexión o datos vacíos recibidos de Kraken.")
