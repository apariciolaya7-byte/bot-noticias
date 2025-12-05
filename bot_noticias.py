
import os
import urllib.parse
import asyncio
import telegram
import feedparser
import httpx
import toml
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, constants
from tinydb import TinyDB, Query

# ==============================================================================
# 🚨 CONFIGURACIÓN - LECTURA DESDE config.toml
# ==============================================================================
# ... (Bloque de configuración TOML existente) ...

try:
    # Intenta cargar la configuración desde el archivo TOML.
    with open('config.toml', 'r') as f:
        config = toml.load(f)
except FileNotFoundError:
    print(
        "🛑 ERROR CRÍTICO: No se encontró el archivo config.toml. Asegúrese de crearlo."
    )
    exit(1)

BOT_TOKEN = config['telegram']['bot_token']
CHAT_ID = config['telegram']['chat_id']
ADMIN_WHATSAPP_PHONE = config['telegram']['admin_whatsapp_phone']
RSS_URLS = config['rss']['urls']
KRAKEN_API = config['api']['kraken_url']
API_TIMEOUT = config['api']['api_timeout']
DB_PATH = config['database']['db_path']

# Inicialización de la base de datos TinyDB
db = TinyDB(DB_PATH)
PriceTable = db.table('prices')
NewsTable = db.table('news')
PriceQuery = Query()
NewsQuery = Query()

# ----------------------------------------------------------------------------------
# 🚨 NUEVA IMPLEMENTACIÓN 1: DICCIONARIO DE PALABRAS CLAVE TEMÁTICAS
# ----------------------------------------------------------------------------------

# Palabras clave para categorizar la noticia por tema (Data Automation, Economía, Tech)
THEME_KEYWORDS = {
    "ECONOMIA": [
        "interés", "reservas", "inflación", "banco central", "recorte",
        "inversión", "pública", "privada", "fmi", "opec", "ceo", "mercado"
    ],
    "TECNOLOGIA": [
        "IA", "LLM", "cloud", "automatización", "5G", "algoritmo",
        "machine learning", "quantum", "openai", "google", "microsoft"
    ],
    "DATA/AUTO": [
        "data pipeline", "ETL", "airflow", "kubernetes", "sql", "databricks",
        "snowflake", "big data", "automatización", "python"
    ]
}

# Definición de pesos para el sentimiento (EXISTENTE)
POSITIVE_KEYWORDS = {
    # ... (Tu diccionario POSITIVE_KEYWORDS existente) ...
    "sube": 1,
    "ganancia": 1,
    "recuperación": 1,
    "aumenta": 1,
    "supera": 1,
    "récord": 2,
    "máximos": 2,
    "disparo": 2,
    "explota": 2,
    "rompe": 2,
    "adopción": 2
}
NEGATIVE_KEYWORDS = {
    # ... (Tu diccionario NEGATIVE_KEYWORDS existente) ...
    "cae": -1,
    "pérdida": -1,
    "baja": -1,
    "colapso": -2,
    "caída libre": -2,
    "desplome": -2,
    "crisis": -2,
    "liquida": -2
}


# ----------------------------------------------------------------------------------
# --- FUNCIONES DE UTILIDAD (SIN CAMBIOS) ---
# ----------------------------------------------------------------------------------
# Colocar esta función junto a las otras utilidades asíncronas
async def send_slack_alert(message: str, client: httpx.AsyncClient):
    """
    Envía un mensaje de error crítico a un canal de Slack
    leyendo la URL desde las Variables de Entorno.
    """
    # Lee la URL desde las variables de entorno, que es la mejor práctica
    SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL') 

    if not SLACK_WEBHOOK_URL:
        print("DEBUG: La variable de entorno SLACK_WEBHOOK_URL no está configurada. Alerta no enviada.")
        return

    payload = {
        "text": f"🚨 BOT CRÍTICO ({datetime.now().strftime('%d/%m %H:%M:%S')}): {message}"
    }

    try:
        # Usa el cliente HTTP asíncrono existente
        await client.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
        print("DEBUG: Alerta de Slack enviada con éxito.")
    except Exception as e:
        # Registramos el error de Slack, pero no detenemos el bot.
        print(f"DEBUG: Error al intentar enviar la alerta de Slack: {e}")

def create_whatsapp_link(message_text: str, phone_number: str) -> str:
    # ... (función existente) ...
    clean_text = message_text.replace('*', '').replace('`',
                                                       '').replace('_', '')
    encoded_text = urllib.parse.quote(clean_text)
    whatsapp_link = f"https://wa.me/{phone_number}?text={encoded_text}"
    return whatsapp_link


def clean_old_news(days_ago: int = 7) -> None:
    # ... (función existente) ...
    try:
        limit_date = datetime.now() - timedelta(days=days_ago)
        limit_iso = limit_date.isoformat()
        NewsTable.remove(NewsQuery.timestamp < limit_iso)
        print(
            f"DEBUG DB: Limpieza de noticias completada. Eliminadas las anteriores a {limit_date.strftime('%Y-%m-%d')}"
        )
    except Exception as e:
        print(f"DEBUG DB: Error en la limpieza de noticias: {e}")


# ----------------------------------------------------------------------------------
# 🚨 NUEVA IMPLEMENTACIÓN 2: LÓGICA DE CATEGORIZACIÓN Y FILTRADO
# ----------------------------------------------------------------------------------


async def get_market_sentiment_and_news_rss(client: httpx.AsyncClient) -> dict:
    # ... (código inicial existente) ...
    news_report_list = []
    sentiment_score = 0
    clean_old_news()

    for rss_url in RSS_URLS:
        try:
            print(f"DEBUG RSS: Procesando URL: {rss_url}")
            rss_response = await client.get(rss_url, timeout=API_TIMEOUT)
            rss_response.raise_for_status()

            feed = feedparser.parse(rss_response.content)

            for entry in feed.entries:
                headline = entry.title
                headline_lower = headline.lower()

                if NewsTable.search(NewsQuery.headline == headline):
                    continue

                # =======================================================
                # 📢 NUEVA LÓGICA: ASIGNACIÓN DE CATEGORÍA TEMÁTICA
                # =======================================================
                category = "GENERAL"
                for cat_name, keywords in THEME_KEYWORDS.items():
                    if category != "GENERAL":
                        break  # Ya tiene una categoría, optimizamos
                    for keyword in keywords:
                        if keyword in headline_lower:
                            category = cat_name
                            break  # Salir del bucle interno

                # =======================================================
                # 📢 LÓGICA DE NEGOCIO: CÁLCULO DE SCORE DE SENTIMIENTO
                # =======================================================
                score = 0
                sugerencia = "📊 Consolidación."

                for keyword, weight in POSITIVE_KEYWORDS.items():
                    if keyword in headline_lower:
                        score += weight

                for keyword, weight in NEGATIVE_KEYWORDS.items():
                    if keyword in headline_lower:
                        score += weight

                # Asignación de la sugerencia (output para el usuario final)
                if score >= 2:
                    sugerencia = "🟢 Fuerte Alcista."
                elif score == 1:
                    sugerencia = "📈 Alcista."
                elif score <= -2:
                    sugerencia = "🔴 Fuerte Bajista."
                elif score == -1:
                    sugerencia = "📉 Bajista."

                sentiment_score += score

                # =======================================================
                # 📢 ALMACENAMIENTO y FILTRADO (FASE L)
                # =======================================================

                # Almacena la noticia y su categoría para persistencia.
                NewsTable.insert({
                    'headline': headline,
                    'category': category,  # <--- CAMBIO: Guardar la categoría
                    'timestamp': datetime.now().isoformat()
                })

                # 🚨 FILTRO DE CALIDAD DE DATOS: Solo agregamos al reporte si NO es GENERAL
                if category != "GENERAL" and len(news_report_list) < 5:
                    news_report_list.append({
                        "titular": headline,
                        "link": entry.link,
                        "sugerencia": sugerencia,
                        "categoria":
                        category,  # <--- CAMBIO: Agregar la categoría
                    })

        except httpx.RequestError as e:
            # ... (Manejo de errores existente) ...
            print(f"DEBUG RSS: ERROR HTTPX al conectar con {rss_url}: {e}")
            continue
        except Exception as e:
            print(f"DEBUG RSS: ERROR GENÉRICO al procesar {rss_url}: {e}")
            continue

    # ... (Retorno de datos existente) ...
    if not news_report_list:
        return ({
            "status":
            "ALERTA: RSS sin noticias nuevas *relevantes* disponibles.",
            "reportes": [],
            "sentiment_score": 0,
            "timestamp": datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        })

    return ({
        "status": "OK",
        "reportes": news_report_list,
        "sentiment_score": sentiment_score,
        "timestamp": datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    })


# ----------------------------------------------------------------------------------
# --- get_crypto_metrics_via_api (SIN CAMBIOS) ---
# ----------------------------------------------------------------------------------


async def get_crypto_metrics_via_api(client: httpx.AsyncClient) -> dict:
    # ... (función existente sin cambios) ...
    try:
        response = await client.get(KRAKEN_API, timeout=API_TIMEOUT)
        print(f"DEBUG: Status Code de Kraken: {response.status_code}")
        response.raise_for_status()
        data = response.json()

        if 'error' in data and data['error']:
            raise ValueError(f"Error de Kraken: {data['error']}")

        ticker_data = data['result']['XXBTZUSD']
        btc_price_float = float(ticker_data['c'][0])
        open_price_float = float(ticker_data['o'])

        btc_price_formatted = f"${btc_price_float:,.2f}"
        change_24h_raw = (
            (btc_price_float - open_price_float) / open_price_float) * 100
        change_24h_clean_str = f"{'+' if change_24h_raw >= 0 else ''}{change_24h_raw:.2f}"
        change_24h_float = change_24h_raw

        momentum_icon = "🚀" if change_24h_float > 0.5 else (
            "📉" if change_24h_float < -0.5 else "🟡")
        change_24h_display = f"{momentum_icon} {change_24h_clean_str}%"

        return ({
            "btc_price_display": btc_price_formatted,
            "btc_price_clean_str": change_24h_clean_str,
            "btc_price_float": btc_price_float,
            "change_24h_display": change_24h_display,
            "change_24h_float": change_24h_float,
            "crypto_status": "OK"
        })

    except httpx.RequestError as e:
        # 1. Alerta a Slack (¡Nuevo!)
        await send_slack_alert(f"Falla HTTPX al conectar con Kraken: {e}", client)
        
        # 2. Registro Local
        print(f"DEBUG: ERROR HTTPX (Kraken) - {e}")
        
        # 3. Retorno de Error
        return ({
            "crypto_status":
            "🔴 ERROR Crypto-API (HTTPX): No se pudo acceder a Kraken.",
            "btc_price_display": "N/D",
            "btc_price_clean_str": "N/D",
            "btc_price_float": 0.0,
            "change_24h_display": "⚠️ N/D",
            "change_24h_float": 0.0
        })
    
    except Exception as e:
        # 1. Alerta a Slack (¡Nuevo!)
        await send_slack_alert(f"Falla General en Kraken: {type(e).__name__}", client)
        
        # 2. Registro Local
        print(f"DEBUG: ERROR General (Kraken) - {e}")
        
        # 3. Retorno de Error
        return ({
            "crypto_status":
            f"🔴 ERROR Crypto (Kraken/Genérico): {type(e).__name__}",
            "btc_price_display": "N/D",
            "btc_price_clean_str": "N/D",
            "btc_price_float": 0.0,
            "change_24h_display": "⚠️ N/D",
            "change_24h_float": 0.0
        })    

        


# ----------------------------------------------------------------------------------
# --- generate_dynamic_tradingview_prompt (SIN CAMBIOS) ---
# ----------------------------------------------------------------------------------


def generate_dynamic_tradingview_prompt(current_price: str,
                                        change_24h_clean_str: str,
                                        sentiment_score: int) -> str:
    # ... (función existente sin cambios) ...
    price_str = current_price.replace('$', '').replace(',', '')

    try:
        change_value = float(
            change_24h_clean_str.replace('+', '').replace('-', ''))

        if change_24h_clean_str.startswith('+') and change_value > 0.5:
            tendencia = "bullish sharp impulsive move with large green candlesticks breaking resistance"
            color_dominante = "vibrant neon green, glowing white"
            momentum_icon = "🚀"
        elif change_24h_clean_str.startswith('-') and change_value > 0.5:
            tendencia = "bearish gradual correction with large red candlesticks pushing support"
            color_dominante = "dark red, subtle orange"
            momentum_icon = "📉"
        else:
            tendencia = "sideways market consolidation range with small doji and spinning top candles, low volatility"
            color_dominante = "neutral grey, blue and slight purple"
            momentum_icon = "🟡"

    except ValueError:
        tendencia = "sideways market consolidation range with small doji and spinning top candles, low volatility"
        color_dominante = "neutral grey, blue and slight purple"
        momentum_icon = "🟡"

    prompt_text = (
        f"A high-definition professional cryptocurrency TradingView dark-mode interface. The main chart shows the BTC/USD pair. "
        f"The price action reflects a **{tendencia}**. Key elements: Japanese candlesticks, visible Exponential Moving Averages (EMA), Volume Profile indicator on the side, and MACD indicator panel below. "
        f"Color Palette: {color_dominante} against the standard TradingView dark background (#131722). "
        f"Atmosphere: Technical, focused, 4k ultra-detailed rendering. "
        f"Data Focus: Current Price: {price_str}, 24h Change: {momentum_icon} {change_24h_clean_str}%. "
        f"Criticial Instruction: The image must be a 16:9 panoramic chart, highly detailed, and look like a **screenshot of a technical analysis platform**."
    )
    return prompt_text


# ----------------------------------------------------------------------------------
# 🚨 NUEVA IMPLEMENTACIÓN 3: FORMATO CON CATEGORÍA
# ----------------------------------------------------------------------------------


async def format_and_send_trading_report(report_data: dict, bot: telegram.Bot,
                                         chat_id: str, whatsapp_phone: str,
                                         image_prompt: str) -> None:

    timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    reportes = report_data.get('reportes', [])
    change_float = report_data.get('change_24h_float', 0.0)
    sentiment_score = report_data.get('sentiment_score', 0)

    # ... (Lógica de Sentimiento Agregado existente) ...
    if sentiment_score >= 3 and change_float > 0.5:
        aggregated_sentiment = "BULLISH (Fuerte Compra) 🟢🟢"
    elif sentiment_score <= -3 and change_float < -0.5:
        aggregated_sentiment = "BEARISH (Fuerte Venta) 🔴🔴"
    elif sentiment_score > 0:
        aggregated_sentiment = "BULLISH LEVE (Acumulación) 🟢"
    elif sentiment_score < 0:
        aggregated_sentiment = "BEARISH LEVE (Distribución) 🔴"
    else:
        aggregated_sentiment = "NEUTRAL (Consolidación) 🟡"

    btc_price = report_data.get('btc_price_display', 'N/D')
    change_24h = report_data.get('change_24h_display', 'N/D')

    # Preparación del listado de noticias
    news_list_text = ""
    if not reportes:
        # CAMBIO en el mensaje de alerta
        news_list_text = "🚨 *ATENCIÓN:* No hay titulares nuevos o relevantes disponibles."
    else:
        for reporte in reportes:
            # 🚨 CAMBIO: Incluir la categoría al inicio del titular.
            news_list_text += (
                f"[{reporte['categoria']}] {reporte['sugerencia']} {reporte['titular']}\n"
            )

    # ... (Resto del mensaje Partes 1 y 2 existente) ...
    message_part_1 = f"""
**═════════════════════════**
📊 **PANEL DE DATOS VITALES | LIVE REPORT** 🤖
_Emitido: {timestamp}_
**═════════════════════════**

📈 **METRICAS CLAVE DE MERCADO**
  🔹 **BTC/USD (Kraken):** `{btc_price}`
  🔹 **Cambio 24h:** `{change_24h}`  
  🔹 **Sentimiento Agregado:** `{aggregated_sentiment}`
---
"""
    message_part_2 = f"""
📰 **FLASH INFORMATIVO - MÁXIMA URGENCIA**
{news_list_text}
---
⚠️ **DISCLAIMER:** Este reporte es generado por IA. Consulte indicadores de *Soporte/Resistencia* y el calendario económico antes de operar.
"""

    await bot.send_message(chat_id=chat_id,
                           text=message_part_1,
                           parse_mode=constants.ParseMode.MARKDOWN)
    await bot.send_message(chat_id=chat_id,
                           text=message_part_2,
                           parse_mode=constants.ParseMode.MARKDOWN)

    # ... (Resto del envío de mensaje para el Prompt y Botón WhatsApp sin cambios) ...
    message_part_3 = f"""
✨ **ACCIÓN REQUERIDA: GENERAR GRÁFICO TÉCNICO** ✨
Copie el siguiente *prompt* y péguelo en el chat de la IA para obtener la visualización del gráfico en tiempo real:
"""
    await bot.send_message(chat_id=chat_id,
                           text=message_part_3,
                           parse_mode=constants.ParseMode.MARKDOWN)

    try:
        await bot.send_message(chat_id=chat_id,
                               text=f"```\n{image_prompt}\n```",
                               parse_mode=constants.ParseMode.HTML)
    except telegram.error.TelegramError as e:
        print(f"ERROR AL ENVIAR TELEGRAM (Parte 4/Prompt): {e}")
        return

    full_message_for_whatsapp = message_part_1 + message_part_2
    whatsapp_share_link = create_whatsapp_link(full_message_for_whatsapp,
                                               whatsapp_phone)

    whatsapp_keyboard = [[
        InlineKeyboardButton("📢 REENVIAR REPORTE ANALÍTICO | WhatsApp",
                             url=whatsapp_share_link)
    ]]
    whatsapp_markup = InlineKeyboardMarkup(whatsapp_keyboard)

    await bot.send_message(
        chat_id=chat_id,
        text=
        "👉 **ACCIÓN DE DIFUSIÓN:** Utiliza el botón para compartir este Reporte Analítico en tus canales.",
        reply_markup=whatsapp_markup,
        parse_mode='Markdown')


# ----------------------------------------------------------------------------------
# --- 5. FUNCIÓN PRINCIPAL DE ORQUESTACIÓN (SIN CAMBIOS) ---
# ----------------------------------------------------------------------------------
async def main():
    # ... (función existente sin cambios) ...
    if BOT_TOKEN is None or CHAT_ID is None:
        print(
            "🛑 ERROR CRÍTICO: Las variables BOT_TOKEN o CHAT_ID no están configuradas en config.toml."
        )
        return

    bot = telegram.Bot(token=BOT_TOKEN)

    async with httpx.AsyncClient() as client:
        crypto_task = get_crypto_metrics_via_api(client)
        rss_task = get_market_sentiment_and_news_rss(client)
        results = await asyncio.gather(crypto_task, rss_task)

        reporte_final = {**results[1], **results[0]}

        btc_price_display = reporte_final.get('btc_price_display', 'N/D')
        change_24h_clean_str = reporte_final.get('btc_price_clean_str', 'N/D')
        sentiment_score = reporte_final.get('sentiment_score', 0)

        image_prompt = generate_dynamic_tradingview_prompt(
            btc_price_display, change_24h_clean_str, sentiment_score)

        await format_and_send_trading_report(reporte_final, bot, CHAT_ID,
                                             ADMIN_WHATSAPP_PHONE,
                                             image_prompt)

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Proceso de automatización completado. Datos consolidados de Kraken y {len(RSS_URLS)} fuentes RSS."
        )


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Proceso terminado por el usuario.")
    except Exception as e:
        print(f"ERROR FATAL EN EJECUCIÓN: {e}")
