import os, base64, json, random, yaml
from aiohttp import web
from urllib.parse import urlparse, unquote, parse_qs
import database_vpn as db

def safe_decode(s):
    try: return base64.decodebytes((s + '=' * (-len(s) % 4)).encode()).decode('utf-8', errors='ignore')
    except: return ""

def get_flag(code):
    if not code or code in ["UN", "??", ""] or len(code) != 2: return "🌐"
    return "".join(chr(ord(c) + 127397) for c in code.upper())

def link_to_clash_dict(url, latency, tier, country, source):
    try:
        flag = get_flag(country)
        tier_icon = "🥇" if tier == 1 else "🥈" if tier == 2 else "🥉"
        pc_mark = "💻" if source == 'pc' else ""
        proto = url.split("://")[0].upper()
        
        # Уникальность
        salt = "".join(random.choices("0123456789", k=2))
        name = f"{tier_icon} {flag}{pc_mark} {latency}ms | {proto} ({salt})"

        if url.startswith("vmess://"):
            try: d = json.loads(base64.b64decode(url[8:] + '==').decode('utf-8', errors='ignore'))
            except: return None
            return {'name': name, 'type': 'vmess', 'server': d.get('add'), 'port': int(d.get('port')), 'uuid': d.get('id'), 'alterId': 0, 'cipher': 'auto', 'udp': True, 'tls': d.get('tls') == 'tls', 'skip-cert-verify': True, 'network': d.get('net', 'tcp'), 'ws-opts': {'path': d.get('path', '/')} if d.get('net') == 'ws' else None}
        
        if url.startswith(("vless://", "trojan://")):
            p = urlparse(url); q = parse_qs(p.query); tp = 'vless' if url.startswith('vless') else 'trojan'
            obj = {'name': name, 'type': tp, 'server': p.hostname, 'port': p.port, 'uuid': p.username or p.password, 'password': p.username or p.password, 'udp': True, 'skip-cert-verify': True, 'tls': q.get('security', [''])[0] in ['tls', 'reality'], 'network': q.get('type', ['tcp'])[0]}
            if tp == 'trojan' and 'uuid' in obj: del obj['uuid']
            if q.get('security', [''])[0] == 'reality':
                obj['servername'] = q.get('sni', [''])[0]; obj['reality-opts'] = {'public-key': q.get('pbk', [''])[0], 'short-id': q.get('sid', [''])[0]}; obj['client-fingerprint'] = 'chrome'
            if obj['network'] == 'ws': obj['ws-opts'] = {'path': q.get('path', ['/'])[0], 'headers': {'Host': q.get('host', [''])[0]}}
            return obj
            
        if url.startswith("ss://"):
            main = url.split("#")[0].replace("ss://", ""); u, s = main.split("@", 1)
            try: d = base64.b64decode(u + '==').decode('utf-8', errors='ignore'); m, pw = d.split(":", 1)
            except: m, pw = u.split(":", 1)
            return {'name': name, 'type': 'ss', 'server': s.split(":")[0], 'port': int(s.split(":")[1].split("/")[0]), 'cipher': m, 'password': pw, 'udp': True}
    except: pass
    return None

def generate_clash_yaml(rows):
    clash_proxies = []
    for idx, r in enumerate(rows):
        # r = (url, latency, tier, country, source)
        obj = link_to_clash_dict(r[0], r[1], r[2], r[3], r[4])
        if obj: clash_proxies.append(obj)
    
    if not clash_proxies: return "proxies: []"

    full_config = {
        "proxies": clash_proxies,
        "proxy-groups": [
            {
                "name": "🚀 VIP Auto Select", 
                "type": "url-test", 
                "url": "https://www.google.com/generate_204", 
                "interval": 600, "timeout": 5000, 
                "proxies": [p['name'] for p in clash_proxies]
            }
        ],
        "rules": ["MATCH,🚀 VIP Auto Select"]
    }
    return yaml.dump(full_config, allow_unicode=True, sort_keys=False)

async def handle_sub(request):
    """Классика (для бекапа)"""
    rows = db.get_classic_sub()
    return web.Response(text=generate_clash_yaml(rows), content_type='text/yaml')

async def handle_vip(request):
    """VIP Ссылка (Гитхаб + ТГ микс)"""
    rows = db.get_vip_sub()
    return web.Response(text=generate_clash_yaml(rows), content_type='text/yaml')

async def start_server():
    app = web.Application()
    app.router.add_get('/sub', handle_sub)
    app.router.add_get('/vip', handle_vip)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
