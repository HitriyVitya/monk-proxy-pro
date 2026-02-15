import os, base64, json, yaml, random, re
from aiohttp import web
from urllib.parse import urlparse, unquote, parse_qs

FINAL_SUB_PATH = "clash_sub.yaml"

def safe_decode(s):
    try:
        s = re.sub(r'[^a-zA-Z0-9+/=]', '', s)
        return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except: return ""

def get_flag(code):
    if not code or code in ["UN", "??", ""] or len(code) != 2: return "🌐"
    try:
        return "".join(chr(ord(c) + 127397) for c in code.upper())
    except: return "🌐"

def is_valid_hex(s):
    if not s: return True
    # Проверка на четную длину и только HEX символы
    return bool(re.match(r'^[0-9a-fA-F]{2,16}$', s)) and len(s) % 2 == 0

def link_to_clash_dict(url, latency, tier, country, source, idx):
    try:
        flag = get_flag(country)
        tier_icon = "🥇" if tier == 1 else "🥈" if tier == 2 else "🥉"
        pc_mark = "💻" if source == 'pc' else ""
        proto = url.split("://")[0].upper()
        
        # Имя без лишнего мусора
        name = f"{tier_icon} {flag}{pc_mark} {latency}ms | {proto} #{idx}"

        if url.startswith("vmess://"):
            d_str = safe_decode(url[8:])
            if not d_str: return None
            d = json.loads(d_str)
            port = d.get('port')
            if not port or not (1 <= int(port) <= 65535): return None
            
            return {
                'name': name, 'type': 'vmess', 'server': d.get('add'),
                'port': int(port), 'uuid': d.get('id'), 'alterId': 0,
                'cipher': 'auto', 'udp': True, 'tls': d.get('tls') == 'tls',
                'skip-cert-verify': True, 'network': d.get('net', 'tcp'),
                'ws-opts': {'path': d.get('path', '/')} if d.get('net') == 'ws' else None
            }
        
        if url.startswith(("vless://", "trojan://")):
            p = urlparse(url)
            q = {k: v[0] for k, v in parse_qs(p.query).items()}
            tp = 'vless' if url.startswith('vless') else 'trojan'
            
            if not p.hostname or not p.port or not (1 <= int(p.port) <= 65535): return None
            
            pwd_uuid = p.username or p.password
            if not pwd_uuid: return None

            obj = {
                'name': name, 'type': tp, 'server': p.hostname, 'port': int(p.port),
                'udp': True, 'skip-cert-verify': True, 'network': q.get('type', 'tcp')
            }
            
            if tp == 'vless': obj['uuid'] = pwd_uuid
            else: obj['password'] = pwd_uuid

            # REALITY / TLS CHECK
            security = q.get('security', '')
            if security == 'reality':
                sid = q.get('sid', '')
                pbk = q.get('pbk', '')
                if not pbk or not is_valid_hex(sid): return None # КИЛЛЕР-ФИКС ТУТ
                
                obj['tls'] = True
                obj['servername'] = q.get('sni', '')
                obj['reality-opts'] = {'public-key': pbk, 'short-id': sid}
                obj['client-fingerprint'] = 'chrome'
            elif security == 'tls' or p.port == 443:
                obj['tls'] = True
                obj['servername'] = q.get('sni', p.hostname)

            if obj.get('network') == 'ws':
                obj['ws-opts'] = {'path': q.get('path', '/'), 'headers': {'Host': q.get('host', p.hostname)}}
            
            return obj
            
        if url.startswith("ss://"):
            main = url.split("#")[0].replace("ss://", "")
            if "@" in main:
                u, s = main.split("@", 1)
                d = safe_decode(u)
                if ":" in d: m, pw = d.split(":", 1)
                else: m, pw = u.split(":", 1)
                host_port = s.split("/")[0].split("?")[0]
                if ":" not in host_port: return None
                host, port = host_port.split(":")
                if not is_valid_port(port): return None # Функция ниже
                return {'name': name, 'type': 'ss', 'server': host, 'port': int(port), 'cipher': m, 'password': pw, 'udp': True}
    except: pass
    return None

def is_valid_port(p):
    try: return 1 <= int(p) <= 65535
    except: return False

def generate_clash_yaml(rows):
    clash_proxies = []
    for idx, r in enumerate(rows):
        # r = (url, latency, tier, country, source)
        obj = link_to_clash_dict(r[0], r[1], r[2], r[3], r[4], idx)
        if obj: clash_proxies.append(obj)
    
    if not clash_proxies: return "proxies: []"
    
    full_config = {
        "proxies": clash_proxies,
        "proxy-groups": [
            {"name": "🚀 Auto Select", "type": "url-test", "url": "https://www.google.com/generate_204", "interval": 600, "timeout": 5000, "proxies": [p['name'] for p in clash_proxies]}
        ],
        "rules": ["MATCH,🚀 Auto Select"]
    }
    # Используем sort_keys=False чтобы proxies был вверху
    return yaml.dump(full_config, allow_unicode=True, sort_keys=False)

async def handle_sub(request):
    import database_vpn as db
    try:
        rows = db.get_classic_sub() # Или get_vip_sub()
        return web.Response(text=generate_clash_yaml(rows), content_type='text/yaml')
    except Exception as e:
        return web.Response(text=f"Error: {e}", status=500)

async def start_server():
    app = web.Application(); app.router.add_get('/sub', handle_sub)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8080).start()
