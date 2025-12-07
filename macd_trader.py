import os
import pandas as pd
import pandas_ta as ta
import ccxt 

# --- CONFIGURACIÓN DE KRAKEN ---
API_KEY = os.getenv('KRAKEN_API_KEY')
SECRET_KEY = os.getenv('KRAKEN_SECRET_KEY')

if not API_KEY or API_KEY.strip() == "" or not SECRET_KEY or SECRET_KEY.strip() == "":
    print("Error: Las variables de entorno de Kraken no están configuradas.")
    exit(1)

    # Inicializar el cliente de Kraken (ccxt maneja la conexión)
    try:
        # Usamos configuración vacía para acceso público
        exchange = ccxt.kraken({
            'enableRateLimit': True,
        }) 
    
        exchange.load_markets() 
        # El SYMBOL real lo definiremos en el bloque if __name__ == '__main__':
    
    except Exception as e:
        print(f"❌ FATAL ERROR CCXT: No se pudo inicializar o conectar a Kraken: {e}")
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

    # ⚠️ ¡SOLUCIÓN! Declara 'exchange' como global
    global exchange

    try:
        klines = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return klines
        
    except ccxt.base.errors.ExchangeError as e:
        # Esto capturará errores como "API key required" o "Invalid nonce"
        print(f"❌ Error de API de Kraken al obtener datos: {e}")
        return None
    except Exception as e:
        print(f"❌ Error general en fetch_ohlcv: {e}")
        return None

# --- Zona de Pruebas ---
if __name__ == '__main__':
    
    # 1. Definir las variables ANTES de usarlas
    SYMBOL = 'XBT/USD' # El ticker más común de Bitcoin en Kraken
    TIMEFRAME = '5m' 
    LIMIT = 100
    
    print(f"[{SYMBOL}] ✅ CCXT Inicializado. Solicitando datos de Kraken en {TIMEFRAME}...")
    
    # 2. Llamar a la función
    klines_data = get_historical_data(SYMBOL, TIMEFRAME, LIMIT) 
    
    if klines_data and len(klines_data) > 0:
        print(f"[{SYMBOL}] ✅ Éxito: Se obtuvieron {len(klines_data)} velas. Calculando MACD...")
        # ... (Aquí iría la llamada a calculate_macd)
        
    else:
        print(f"[{SYMBOL}] ❌ Fallo en la conexión o datos vacíos recibidos de Kraken.")