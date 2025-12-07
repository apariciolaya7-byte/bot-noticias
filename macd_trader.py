import os
import pandas as pd
import pandas_ta as ta
import ccxt # <--- ¡Nueva Importación!

# --- CONFIGURACIÓN DE KRAKEN ---
# Las variables de entorno son la forma más segura de manejar credenciales
# Usamos las mismas variables, pero ahora se conectarán a Kraken.
# --- CONFIGURACIÓN DE KRAKEN ---
API_KEY = os.getenv('KRAKEN_API_KEY')
SECRET_KEY = os.getenv('KRAKEN_SECRET_KEY')

# AÑADIR ESTA VERIFICACIÓN ADICIONAL PARA ELIMINAR ESPACIOS INVISIBLES
if not API_KEY or API_KEY.strip() == "" or not SECRET_KEY or SECRET_KEY.strip() == "":
    print("Error: Las variables de entorno de Kraken no están configuradas.")
    exit(1)

# Inicializar el cliente de Kraken (ccxt maneja la conexión)
try:
    exchange = ccxt.kraken({
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'enableRateLimit': True,
    })
    exchange.load_markets() # <--- ¡Añadir esto para probar la conexión inmediatamente!
except Exception as e:
    # Si falla la inicialización o la carga de mercados, imprimimos el error y salimos.
    print(f"❌ FATAL ERROR CCXT: No se pudo inicializar o conectar a Kraken: {e}")
    exit(1) # <--- Detiene el script con un código de error visible


# 2. Función para Obtener Datos de 5 Minutos (Usando ccxt)
def get_historical_data(symbol, timeframe, limit):
    """
    Obtiene datos de velas (candlesticks) de Kraken usando ccxt.
    :param symbol: Par de trading (ej: 'BTC/USD').
    :param timeframe: Temporalidad (ej: '5m').
    :param limit: Número de velas (ej: 100).
    :return: Lista de velas (OHLCV).
    """
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
    # Kraken usa el formato XBT/USD para Bitcoin, pero el formato estándar es BTC/USDT.
    # Usaremos el formato estándar para mejor portabilidad.
    SYMBOL = 'BTC/USDT' 
    
    # La estrategia de scalping es en 5 minutos
    TIMEFRAME = '5m' 
    
    # Necesitamos unas 100 velas para el MACD y algo de margen.
    LIMIT = 100
    
    # ... (El resto de la lógica de pandas y MACD sigue igual)
    # Asegúrate de cambiar Client.KLINE_INTERVAL_5MINUTE por '5m' en la llamada a get_historical_data