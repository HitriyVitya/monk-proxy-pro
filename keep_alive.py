import base64
import json
import yaml
from aiohttp import web
from urllib.parse import urlparse, unquote, parse_qs
import database_vpn as db

PROXY_CACHE = "proxies: []" # Дефолт, если база пустая

def safe_b64(s):
    try:
        s = s.strip().replace('\r', '').replace('\n', '')
        return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except: return ""

def link_to_clash_dict(url, latency, is_ai, country):
    """Превращает ссылку в словарь для Clash"""
    flag = country if country and len(country) == 2 else "🏳️"
    if flag != "🏳️": # Превращаем код DE в эмодзи
        flag = "".join(chr(ord(c) + 127397) for c in flag.upper())
    
    ai_tag = " ✨ AI" if is_ai else ""
    # Пытаемся вытащить IP для уникальности имени
    try:
        srv_ip = url.split('@')[-1].split(':')[0]
        srv_ip = srv_ip.split('.')[-1] # Только последний октет для краткости
    except: srv_ip = "srv"
    
    name = f"{flag}{ai_tag} {latency}ms | {srv_ip}"

    try:
        if url.startswith("vmess://"):
            d = json.loads(safe_b64(url[8:]))
            return {
                'name': name, 'type': 'vmess', 'server': d.get('add'),
                'port': int(d.get('port')), 'uuid': d.get('id'), 'alterId': 0,
                'cipher': 'auto', 'udp': True, 'tls': d.get('tls') == 'tls',
                'skip-cert-verify': True, 'network': d.get('net', 'tcp')
            }
        
        if url.startswith(("vless://", "trojan://")):
            p = urlparse(url); q = parse_qs(p.query)
            tp = 'vless' if url.startswith('vless') else 'trojan'
            obj = {
                'name': name, 'type': tp, 'server': p.hostname, 'port': p.port,
                'uuid': p.username or p.password, 'password': p.username or p.password,
                'udp': True, 'skip-cert-verify': True,
                'tls': q.get('security', [''])[0] in ['tls', 'reality'],
                'network': q.get('type', ['tcp'])[0]
            }
            if tp == 'trojan' and 'uuid' in obj: del obj['uuid']
            if q.get('security', [''])[0] == 'reality':
                obj['servername'] = q.get('sni', [''])[0]
                obj['reality-opts'] = {'public-key': q.get('pbk', [''])[0], 'short-id': q.get('sid', [''])[0]}
                obj['client-fingerprint'] = 'chrome'
            return obj

        if url.startswith("ss://"):
            main = url.split("#")[0].replace("ss://", "")
            if "@" in main:
                u, s = main.split("@", 1)
                d = safe_b64(u)
                m, pw = d.split(":", 1) if ":" in d else (u.split(":", 1) if ":" in u else ("aes-256-gcm", u))
                return {
                    'name': name, 'type': 'ss', 'server': s.split(":")[0],
                    'port': int(s.split(":")[1].split("/")[0]), 'cipher': m, 'password': pw, 'udp': True
                }
    except: pass
    return None

def update_internal_cache():
    """Собирает YAML и кладет в память"""
    global PROXY_CACHE
    try:
        # Достаем данные: (url, is_ai, latency, country)
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("SELECT url, latency, is_ai, country FROM vpn_proxies WHERE fails < 2 AND latency < 2500 ORDER BY is_ai DESC, latency ASC LIMIT 300")
        rows = c.fetchall()
        conn.close()

        clash_proxies = []
        for r in rows:
            obj = link_to_clash_dict(r[0], r[1], r[2], r[3])
            if obj:
                # Проверка на уникальность имени (Clash ругается на дубли)
                orig_name = obj['name']
                count = 1
                while any(p['name'] == obj['name'] for p in clash_proxies):
                    obj['name'] = f"{orig_name} ({count})"
                    count += 1
                clash_proxies.append(obj)
        
        if clash_proxies:
            # Генерируем финальный YAML
            data = {'proxies': clash_proxies}
            PROXY_CACHE = yaml.dump(data, allow_unicode=True, sort_keys=False)
    except Exception as e:
        print(f"Cache Error: {e}")

async def handle_sub(request):
    return web.Response(text=PROXY_CACHE, content_type='text/yaml')

async def handle_home(request):
    return web.Response(text="Iron Monk Center is Running!")

async def start_server():
    app = web.Application()
    app.router.add_get('/', handle_home)
    app.router.add_get('/sub', handle_sub)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
