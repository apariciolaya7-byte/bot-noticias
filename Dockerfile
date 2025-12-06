# 1. BASE: Imagen base de Python, ligera y optimizada
FROM python:3.11-slim

# 3. DEPENDENCIAS DEL SISTEMA: Incluimos las herramientas de compilación de Debian (apt)
#    Esto es CRUCIAL para pandas-ta, numpy y otras extensiones.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. METADATOS: Etiqueta al mantenedor
LABEL maintainer="junir"

# 3. WORKDIR: Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# 4. DEPENDENCIAS: Copia el archivo de requisitos e instala las dependencias
# Asumiendo que tienes un archivo 'requirements.txt' con httpx, python-telegram-bot, etc.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. CODIGO: Copia todo el código fuente del bot al contenedor
COPY . .

# 6. ENTRADA: Define el comando que se ejecuta al iniciar el contenedor
CMD ["python", "bot_noticias.py"]