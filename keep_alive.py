import base64, json, os
from aiohttp import web
from urllib.parse import urlparse, unquote, parse_qs

FINAL_SUB_PATH = "clash_sub.yaml"

def safe_decode(s):
    try: return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except: return ""

def link_to_clash_dict(url, latency, is_ai, country):
    try:
        flag = "🏳️" # Можно добавить GeoIP позже
        ai_tag = " ✨ AI" if is_ai else ""
        try: srv = url.split('@')[-1].split(':')[0].split('.')[-1]
        except: srv = "srv"
        name = f"{flag}{ai_tag} {latency}ms | {srv}"

        if url.startswith("vmess://"):
            d = json.loads(safe_decode(url[8:]))
            return {'name': name, 'type': 'vmess', 'server': d.get('add'), 'port': int(d.get('port')), 'uuid': d.get('id'), 'alterId': 0, 'cipher': 'auto', 'udp': True, 'tls': d.get('tls') == 'tls', 'skip-cert-verify': True, 'network': d.get('net', 'tcp')}
        if url.startswith(("vless://", "trojan://")):
            p = urlparse(url); q = parse_qs(p.query); tp = 'vless' if url.startswith('vless') else 'trojan'
            obj = {'name': name, 'type': tp, 'server': p.hostname, 'port': p.port, 'uuid': p.username or p.password, 'password': p.username or p.password, 'udp': True, 'skip-cert-verify': True, 'tls': q.get('security', [''])[0] in ['tls', 'reality'], 'network': q.get('type', ['tcp'])[0]}
            if tp == 'trojan' and 'uuid' in obj: del obj['uuid']
            if q.get('security', [''])[0] == 'reality':
                obj['servername'] = q.get('sni', [''])[0]; obj['reality-opts'] = {'public-key': q.get('pbk', [''])[0], 'short-id': q.get('sid', [''])[0]}; obj['client-fingerprint'] = 'chrome'
            return obj
    except: pass
    return None

async def handle_sub(request):
    if os.path.exists(FINAL_SUB_PATH):
        return web.FileResponse(FINAL_SUB_PATH)
    return web.Response(text="proxies: []", content_type='text/yaml')

async def start_server():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Alive"))
    app.router.add_get('/sub', handle_sub)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
