from flask import Flask, Response, request, stream_with_context, render_template
import requests
from urllib.parse import urljoin, urlparse
import time
import logging
import os

# Configure logging for debugging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")

# Headers para u.m3uts.xyz
HEADERS_UM3U = {
    "Accept-Encoding": "gzip",
    "Connection": "Keep-Alive",
    "Host": "u.m3uts.xyz",
    "User-Agent": "Ultimate Player/1.0.7",
    "X-Did": "fb6fd3030f4146b7",
    "X-Hash": "OV_WTEnM28mJG4gKENQClNMZXjOaxhJ_yJRpTAMSPCMa2JUik77bEWS12kqT00GVooxoYCKoFM39OSDtHCokRA",
    "X-Version": "10/1.0.7"
}

BASE_URL_UM3U = "http://u.m3uts.xyz/"

@app.route('/')
def index():
    """Show proxy server status page"""
    return render_template('index.html', 
                         host_url=request.host_url,
                         base_url=BASE_URL_UM3U)

@app.route('/<path:url_path>')
def um3u_proxy(url_path):
    """
    Main proxy handler for multimedia streaming
    Supports M3U8 playlists and video segments with URL rewriting
    """
    # Parse the URL path to determine target
    parts = url_path.split("/", 1)
    if len(parts) == 2 and "." in parts[0]:
        domain, path = parts
        target_url = f"http://{domain}/{path}"
    else:
        target_url = urljoin(BASE_URL_UM3U, url_path)

    logger.info(f"[PROXY] Cliente pidió: /{url_path}")
    logger.info(f"[PROXY] Reenviando a: {target_url}")

    # Use specific headers for u.m3uts.xyz domain
    headers = HEADERS_UM3U if "u.m3uts.xyz" in target_url else {"User-Agent": "Ultimate Player/1.0.7"}

    try:
        start_time = time.time()
        r = requests.get(target_url, headers=headers, stream=True, timeout=30)
        content_type = r.headers.get('Content-Type', '')

        logger.info(f"[PROXY] Status: {r.status_code}, Content-Type: {content_type}")

        # Handle M3U8 playlist files with URL rewriting
        if url_path.endswith(".m3u8"):
            playlist = r.text
            logger.debug("Contenido playlist recibido (primeros 500 caracteres):\n%s", playlist[:500])

            new_playlist = ""
            for line in playlist.splitlines():
                if line.strip() and not line.startswith("#"):
                    # Rewrite URLs to point through this proxy
                    abs_url = line.strip()
                    parsed = urlparse(abs_url)
                    proxied_url = request.host_url + parsed.netloc + parsed.path
                    if parsed.query:
                        proxied_url += "?" + parsed.query
                    new_playlist += proxied_url + "\n"
                else:
                    new_playlist += line + "\n"

            # Clean up response headers
            excluded_headers = ['content-encoding', 'transfer-encoding', 'connection']
            response_headers = [(k, v) for k, v in r.headers.items() if k.lower() not in excluded_headers]

            return Response(new_playlist, content_type="application/vnd.apple.mpegurl", headers=response_headers)

        # Handle video segments (.ts files) with streaming
        if url_path.endswith(".ts"):
            logger.info(f"[PROXY] Segmento de vídeo detectado: {url_path}")

            def generate():
                bytes_sent = 0
                try:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            bytes_sent += len(chunk)
                            yield chunk
                finally:
                    elapsed = time.time() - start_time
                    logger.info(f"[PROXY] Enviado {bytes_sent} bytes en {elapsed:.2f} segundos para {url_path}")

            # Clean up problematic headers for streaming
            excluded_headers = ['connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
                                'te', 'trailers', 'transfer-encoding', 'upgrade']
            response_headers = [(k, v) for k, v in r.headers.items() if k.lower() not in excluded_headers]

            return Response(stream_with_context(generate()), content_type=content_type, headers=response_headers)

        # Handle other content types with streaming
        return Response(
            stream_with_context(r.iter_content(chunk_size=1024)),
            content_type=content_type,
            headers=[(k, v) for k, v in r.headers.items() 
                    if k.lower() not in ['connection', 'transfer-encoding']]
        )

    except requests.exceptions.RequestException as e:
        logger.error(f"[PROXY] Error en request: {str(e)}")
        return Response(f"Error de proxy: {str(e)}", status=502, content_type="text/plain")
    except Exception as e:
        logger.error(f"[PROXY] Error interno: {str(e)}")
        return Response(f"Error interno del servidor: {str(e)}", status=500, content_type="text/plain")

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors with informative message"""
    return render_template('index.html', 
                         error="Ruta no encontrada. Use el proxy añadiendo la URL después del dominio.",
                         host_url=request.host_url,
                         base_url=BASE_URL_UM3U), 404

if __name__ == '__main__':
    # Run on port 5000 as per Flask guidelines, with threading for concurrent connections
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=True)
