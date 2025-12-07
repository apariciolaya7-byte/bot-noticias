import os
import pandas as pd
import pandas_ta as ta
import ccxt
import traceback
from ccxt.base.errors import ExchangeError  # ✅ Import correcto

# --- CONFIGURACIÓN DE KRAKEN ---
API_KEY = os.getenv('KRAKEN_API_KEY')
SECRET_KEY = os.getenv('KRAKEN_SECRET_KEY')

if not API_KEY or API_KEY.strip() == "" or not SECRET_KEY or SECRET_KEY.strip() == "":
    print("Error: Las variables de entorno de Kraken no están configuradas.")
    exit(1)

# 🚨 Inicializar 'exchange' fuera del if
exchange = None

try:
    # 1. Creamos la instancia
    exchange = ccxt.kraken({
        'enableRateLimit': True,
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
    })

    exchange.load_markets()
    # El SYMBOL real lo definiremos en el bloque if __name__ == '__main__':

except Exception as e:
    print("🚨🚨🚨 ¡¡ERROR CRÍTICO AL INICIALIZAR CCXT!! 🚨🚨🚨")
    print("-------------------------------------------------")
    print(f"Razón: {e}")
    traceback.print_exc()
    print("-------------------------------------------------")
    exit(1)


# 2. Función para Obtener Datos de 5 Minutos (Usando ccxt)
def get_historical_data(symbol, timeframe, limit):
    """
    Obtiene datos de velas (candlesticks) de Kraken usando ccxt.
    :param symbol: Par de trading (ej: 'XBT/USD').
    :param timeframe: Temporalidad (ej: '5m').
    :param limit: Número de velas (ej: 100).
    :return: Lista de velas (OHLCV).
    """
    global exchange

    try:
        klines = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return klines

    except ExchangeError as e:  # ✅ Uso correcto
        print("🚨🚨 ¡ERROR DE LA API DE KRAKEN! REVISA LLAVES/PERMISOS! 🚨🚨")
        print(f"Mensaje de Kraken: {e}")
        return None

    except Exception as e:
        print("🚨🚨 ¡ERROR GENERAL INESPERADO EN get_historical_data! 🚨🚨")
        print(f"Razón: {e}")
        traceback.print_exc()
        return None


# --- Zona de Pruebas ---
if __name__ == '__main__':

    SYMBOL = 'BTC/USD'
    TIMEFRAME = '5m'
    LIMIT = 100

    print(f"[{SYMBOL}] ✅ CCXT Inicializado. Solicitando datos de Kraken en {TIMEFRAME}...")

    klines_data = get_historical_data(SYMBOL, TIMEFRAME, LIMIT)

    if klines_data and len(klines_data) > 0:
        print(f"[{SYMBOL}] ✅ Éxito: Se obtuvieron {len(klines_data)} velas. Calculando MACD...")
        # Aquí iría la llamada a calculate_macd
    else:
        print(f"[{SYMBOL}] ❌ Fallo en la conexión o datos vacíos recibidos de Kraken.")