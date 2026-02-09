import os
from aiohttp import web
import base64, json
from urllib.parse import urlparse, unquote, parse_qs

FINAL_SUB_PATH = "clash_sub.yaml"

def safe_decode(s):
    try: return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except: return ""

def link_to_clash_dict(url, latency, is_ai, country):
    try:
        # ПРЕВРАЩАЕМ КОД СТРАНЫ В ФЛАГ
        if country and len(country) == 2 and country != "UN":
            flag = "".join(chr(ord(c) + 127397) for c in country.upper())
        else:
            flag = "🇺🇳"
            
        ai_tag = " ✨ AI" if is_ai else ""
        try: srv = url.split('@')[-1].split(':')[0].split('.')[-1]
        except: srv = "srv"
        name = f"{flag}{ai_tag} {latency}ms | {srv}"

        if url.startswith("vmess://"):
            d = json.loads(safe_decode(url[8:]))
            return {'name': name, 'type': 'vmess', 'server': d.get('add'), 'port': int(d.get('port')), 'uuid': d.get('id'), 'alterId': 0, 'cipher': 'auto', 'udp': True, 'tls': d.get('tls') == 'tls', 'skip-cert-verify': True, 'network': d.get('net', 'tcp'), 'ws-opts': {'path': d.get('path', '/')} if d.get('net') == 'ws' else None}
        if url.startswith(("vless://", "trojan://")):
            p = urlparse(url); q = parse_qs(p.query); tp = 'vless' if url.startswith('vless') else 'trojan'
            obj = {'name': name, 'type': tp, 'server': p.hostname, 'port': p.port, 'uuid': p.username or p.password, 'password': p.username or p.password, 'udp': True, 'skip-cert-verify': True, 'tls': q.get('security', [''])[0] in ['tls', 'reality'], 'network': q.get('type', ['tcp'])[0]}
            if tp == 'trojan' and 'uuid' in obj: del obj['uuid']
            if q.get('security', [''])[0] == 'reality':
                obj['servername'] = q.get('sni', [''])[0]; obj['reality-opts'] = {'public-key': q.get('pbk', [''])[0], 'short-id': q.get('sid', [''])[0]}; obj['client-fingerprint'] = 'chrome'
            return obj
        if url.startswith("ss://"):
            main = url.split("#")[0].replace("ss://", "")
            if "@" in main:
                u, s = main.split("@", 1); d = safe_decode(u)
                m, pw = d.split(":", 1) if ":" in d else (u.split(":", 1) if ":" in u else ("aes-256-gcm", u))
                return {'name': name, 'type': 'ss', 'server': s.split(":")[0], 'port': int(s.split(":")[1].split("/")[0]), 'cipher': m, 'password': pw, 'udp': True}
    except: pass
    return None

async def handle_sub(request):
    """Отдает файл с ПРАВИЛЬНЫМИ заголовками для Клэша"""
    if os.path.exists(FINAL_SUB_PATH):
        # Добавляем заголовки, чтобы клиент не вис
        headers = {
            'Content-Type': 'text/yaml; charset=utf-8',
            'Cache-Control': 'no-cache',
            'Content-Disposition': 'attachment; filename="proxies.yaml"',
            'Subscription-Userinfo': 'upload=0;download=0;total=10737418240;expire=0' # Фейковая инфа о трафике для красоты
        }
        return web.FileResponse(FINAL_SUB_PATH, headers=headers)
    return web.Response(text="proxies: []", content_type='text/yaml')

async def start_server():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Monk Hub is Live"))
    app.router.add_get('/sub', handle_sub)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
