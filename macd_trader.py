import os
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
import ccxt

# 1. Configuración de Variables de Entorno
# Las variables de entorno son la forma más segura de manejar credenciales
# Debes configurar BINANCE_API_KEY y BINANCE_SECRET_KEY en tu entorno de CodeSpace/Docker
export KRAKEN_API_KEY="TU_CLAVE_AQUI"
export KRAKEN_SECRET_KEY="TU_SECRETO_AQUI"

if not API_KEY or not SECRET_KEY:
    print("Error: Las variables de entorno KRAKEN_API_KEY o KRAKEN_SECRET_KEY no están configuradas.")
    exit(1)

# Inicializar el cliente de Binance
client = ccxt.kraken(API_KEY, SECRET_KEY)

# 2. Función para Obtener Datos de 5 Minutos
def get_historical_data(symbol, interval, lookback):
    """
    Obtiene datos de velas (candlesticks) de Kraken.
    :param symbol: Par de trading (ej: 'BTCUSDT').
    :param interval: Temporalidad (ej: Client.KLINE_INTERVAL_5MINUTE).
    :param lookback: Número de periodos a mirar (ej: "100 minutes ago").
    :return: Lista de velas (OHLCV).
    """
    try:
        # Petición a la API de Binance
        klines = client.get_historical_klines(symbol, interval, lookback)
        
        # Una vela es: [Tiempo_Apertura, Apertura, Máximo, Mínimo, Cierre, Volumen, ...]
        return klines
        
    except krakenAPIException as e:
        print(f"Error de API de Binance: {e}")
        return None
    except krakenRequestException as e:
        print(f"Error de conexión de Binance: {e}")
        return None

# --- Zona de Pruebas ---
if __name__ == '__main__':
    # Usaremos BTCUSDT como ejemplo
    SYMBOL = 'BTCUSDT' 
    
    # La estrategia de scalping es en 5 minutos
    INTERVAL = Client.KLINE_INTERVAL_5MINUTE 
    
    # Necesitamos unas 26 velas para el MACD (26 periodos) + un margen.
    LOOKBACK = "1 hour ago" 
    
    print(f"Obteniendo datos de {SYMBOL} en la temporalidad de {INTERVAL}...")
    data = get_historical_data(SYMBOL, INTERVAL, LOOKBACK)
    
    if data:
        print(f"Datos obtenidos con éxito. Número de velas: {len(data)}")
        # Imprimimos la última vela para verificar
        print("Última vela (Cierre):", data[-1][4]) 
    else:
        print("Fallo al obtener datos.")