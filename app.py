from flask import Flask, Response, request, stream_with_context, render_template
import requests
from urllib.parse import urljoin, urlparse
import time
import logging
import os

# Configurar logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")

# Headers para distintos hosts
HEADERS_TV_M3U = {
    "Accept-Encoding": "gzip",
    "Connection": "Keep-Alive",
    "Content-Type": "application/x-www-form-urlencoded",
    "Host": "tv.m3uts.xyz",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 14; RMX3630 Build/UKQ1.230924.001)"
}

HEADERS_MAGMA = {
    "Connection": "Keep-Alive",
    "Host": "magmaplayer.com",
    "User-Agent": "Magma Player/9",
    "X-Did": "fb6fd3030f4146b7",
    "X-Hash": "Aquí_va_el_hash_correcto",  # Actualiza con tu hash real
    "X-Version": "9/1.0.8"
}

HEADERS_UM3U = {
    "Accept-Encoding": "gzip",
    "Connection": "Keep-Alive",
    "Host": "u.m3uts.xyz",
    "User-Agent": "Ultimate Player/1.0.7",
    "X-Did": "fb6fd3030f4146b7",
    "X-Hash": "OV_WTEnM28mJG4gKENQClNMZXjOaxhJ_yJRpTAMSPCMa2JUik77bEWS12kqT00GVooxoYCKoFM39OSDtHCokRA",
    "X-Version": "10/1.0.7"
}

BASE_URL_TV_M3U = "http://tv.m3uts.xyz/"
BASE_URL_UM3U = "http://u.m3uts.xyz/"

# Ruta de status/index
@app.route('/')
def index():
    return render_template('index.html', 
                           host_url=request.host_url,
                           base_url=BASE_URL_UM3U)

# Ruta específica para tv.m3uts.xyz stream/gen/<canal_id>
@app.route('/tv.m3uts.xyz/stream/gen/<canal_id>', methods=["GET"])
def proxy_tv_gen(canal_id):
    payload = {
        "id": canal_id,
        "cast": "false",
        "device": "fb6fd3030f4146b7",
        "code": "200"
    }

    logger.info(f"[PROXY] POST a {BASE_URL_TV_M3U}stream/gen/{canal_id} con payload {payload}")
    r_post = requests.post(f"{BASE_URL_TV_M3U}stream/gen/{canal_id}", headers=HEADERS_TV_M3U, data=payload)
    if r_post.status_code != 200:
        return f"Error {r_post.status_code} en POST", 500

    url_m3u8 = r_post.text.strip()
    logger.info(f"[PROXY] URL m3u8 recibida: {url_m3u8}")

    r_get = requests.get(url_m3u8, headers=HEADERS_MAGMA)
    if r_get.status_code != 200:
        return f"Error {r_get.status_code} al obtener m3u8", 500

    playlist = r_get.text
    new_playlist = ""

    for line in playlist.splitlines():
        if line.strip() and not line.startswith("#"):
            abs_url = line.strip()
            parsed = urlparse(abs_url)
            proxied_url = request.host_url + parsed.netloc + parsed.path
            if parsed.query:
                proxied_url += "?" + parsed.query
            new_playlist += proxied_url + "\n"
        else:
            new_playlist += line + "\n"

    return Response(new_playlist, content_type="application/vnd.apple.mpegurl")

# Proxy general para multimedia y streaming
@app.route('/<path:url_path>', methods=["GET"])
def general_proxy(url_path):
    # Determinar target URL para u.m3uts.xyz o general
    parts = url_path.split("/", 1)
    if len(parts) == 2 and "." in parts[0]:
        domain, path = parts
        target_url = f"http://{domain}/{path}"
    else:
        # Por defecto usa u.m3uts.xyz base URL para paths sin dominio
        target_url = urljoin(BASE_URL_UM3U, url_path)

    logger.info(f"[PROXY] Cliente pidió: /{url_path}")
    logger.info(f"[PROXY] Reenviando a: {target_url}")

    # Definir headers según dominio
    if "magmaplayer.com" in target_url:
        headers = HEADERS_MAGMA
    elif "u.m3uts.xyz" in target_url:
        headers = HEADERS_UM3U
    else:
        # User-Agent genérico para otros
        headers = {"User-Agent": "Ultimate Player/1.0.7"}

    try:
        start_time = time.time()
        r = requests.get(target_url, headers=headers, stream=True, timeout=(10, 300))
        content_type = r.headers.get('Content-Type', '')

        logger.info(f"[PROXY] Status: {r.status_code}, Content-Type: {content_type}")

        if url_path.endswith(".m3u8"):
            playlist = r.text
            logger.debug("Contenido playlist recibido (primeros 500 caracteres):\n%s", playlist[:500])

            new_playlist = ""
            for line in playlist.splitlines():
                if line.strip() and not line.startswith("#"):
                    abs_url = line.strip()
                    parsed = urlparse(abs_url)
                    proxied_url = request.host_url + parsed.netloc + parsed.path
                    if parsed.query:
                        proxied_url += "?" + parsed.query
                    new_playlist += proxied_url + "\n"
                else:
                    new_playlist += line + "\n"

            excluded_headers = ['content-encoding', 'transfer-encoding', 'connection']
            response_headers = [(k, v) for k, v in r.headers.items() if k.lower() not in excluded_headers]

            return Response(new_playlist, content_type="application/vnd.apple.mpegurl", headers=response_headers)

        if url_path.endswith(".ts"):
            logger.info(f"[PROXY] Segmento de vídeo detectado: {url_path}")

            def generate():
                bytes_sent = 0
                try:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            bytes_sent += len(chunk)
                            yield chunk
                        else:
                            time.sleep(1)
                            yield b'\n'
                finally:
                    elapsed = time.time() - start_time
                    logger.info(f"[PROXY] Enviado {bytes_sent} bytes en {elapsed:.2f} segundos para {url_path}")

            excluded_headers = ['connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
                                'te', 'trailers', 'transfer-encoding', 'upgrade']
            response_headers = [(k, v) for k, v in r.headers.items() if k.lower() not in excluded_headers]

            return Response(stream_with_context(generate()), content_type=content_type, headers=response_headers)

        # Otros tipos de contenido
        return Response(
            stream_with_context(r.iter_content(chunk_size=1024)),
            content_type=content_type,
            headers=[(k, v) for k, v in r.headers.items() if k.lower() not in ['connection', 'transfer-encoding']]
        )

    except requests.exceptions.RequestException as e:
        logger.error(f"[PROXY] Error en request: {str(e)}")
        return Response(f"Error de proxy: {str(e)}", status=502, content_type="text/plain")
    except Exception as e:
        logger.error(f"[PROXY] Error interno: {str(e)}")
        return Response(f"Error interno del servidor: {str(e)}", status=500, content_type="text/plain")

@app.errorhandler(404)
def not_found(error):
    return render_template('index.html',
                           error="Ruta no encontrada. Use el proxy añadiendo la URL después del dominio.",
                           host_url=request.host_url,
                           base_url=BASE_URL_UM3U), 404


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host='0.0.0.0', port=port, threaded=True, debug=debug)
