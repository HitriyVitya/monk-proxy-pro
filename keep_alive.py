import os, base64, json, yaml, random, re
from aiohttp import web
from urllib.parse import urlparse, unquote, parse_qs

FINAL_SUB_PATH = "clash_sub.yaml"

def safe_decode(s):
    try: return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except: return ""

def get_flag(code):
    if not code or code in ["UN", "??", ""] or len(code) != 2: return "🌐"
    try:
        return "".join(chr(ord(c) + 127397) for c in code.upper())
    except: return "🌐"

def is_valid_port(port):
    try:
        p = int(port)
        return 1 <= p <= 65535
    except: return False

def is_valid_hex(s):
    # Проверка для ShortID (только 0-9, a-f)
    if not s: return True # Пустой тоже ок
    return bool(re.match(r'^[0-9a-fA-F]+$', s))

def link_to_clash_dict(url, latency, tier, country, source, idx):
    try:
        flag = get_flag(country)
        tier_icon = "🥇" if tier == 1 else "🥈" if tier == 2 else "🥉"
        pc_mark = "💻" if source == 'pc' else ""
        proto = url.split("://")[0].upper()
        
        # Защита от дублей имени
        name = f"{tier_icon} {flag}{pc_mark} {latency}ms | {proto} (#{idx})"

        if url.startswith("vmess://"):
            d = json.loads(safe_decode(url[8:]))
            port = d.get('port')
            if not is_valid_port(port): return None
            
            return {
                'name': name, 'type': 'vmess', 
                'server': d.get('add'), 'port': int(port), 
                'uuid': d.get('id'), 'alterId': 0, 'cipher': 'auto', 
                'udp': True, 'tls': d.get('tls') == 'tls', 
                'skip-cert-verify': True, 
                'network': d.get('net', 'tcp'), 
                'ws-opts': {'path': d.get('path', '/'), 'headers': {'Host': d.get('host', '')}} if d.get('net') == 'ws' else None
            }
        
        if url.startswith(("vless://", "trojan://")):
            p = urlparse(url); q = parse_qs(p.query)
            tp = 'vless' if url.startswith('vless') else 'trojan'
            
            if not p.hostname or not is_valid_port(p.port): return None
            
            uuid_pass = p.username or p.password
            if not uuid_pass: return None

            obj = {
                'name': name, 'type': tp, 
                'server': p.hostname, 'port': p.port, 
                'uuid': uuid_pass, 'password': uuid_pass, 
                'udp': True, 'skip-cert-verify': True, 
                'tls': q.get('security', [''])[0] in ['tls', 'reality'], 
                'network': q.get('type', ['tcp'])[0]
            }
            
            if tp == 'trojan' and 'uuid' in obj: del obj['uuid']
            
            # --- ВАЖНАЯ ЗАЩИТА REALITY ---
            if q.get('security', [''])[0] == 'reality':
                sid = q.get('sid', [''])[0]
                pbk = q.get('pbk', [''])[0]
                
                # Если short-id кривой — выкидываем сервер, чтобы не ломать подписку
                if not is_valid_hex(sid): return None
                if not pbk: return None # Без ключа Reality не работает
                
                obj['servername'] = q.get('sni', [''])[0]
                obj['reality-opts'] = {'public-key': pbk, 'short-id': sid}
                obj['client-fingerprint'] = 'chrome'
            
            if obj['network'] == 'ws':
                obj['ws-opts'] = {'path': q.get('path', ['/'])[0], 'headers': {'Host': q.get('host', [''])[0]}}
            return obj
            
        if url.startswith("ss://"):
            main = url.split("#")[0].replace("ss://", "")
            if "@" in main:
                u, s = main.split("@", 1)
                try: d = safe_decode(u); m, pw = d.split(":", 1)
                except: m, pw = u.split(":", 1)
                
                host = s.split(":")[0]
                port_str = s.split(":")[1].split("/")[0]
                
                if not is_valid_port(port_str): return None
                
                return {
                    'name': name, 'type': 'ss', 
                    'server': host, 'port': int(port_str), 
                    'cipher': m, 'password': pw, 'udp': True
                }
    except: pass
    return None

def generate_clash_yaml(rows):
    clash_proxies = []
    for idx, r in enumerate(rows):
        # r = (url, latency, tier, country, source)
        obj = link_to_clash_dict(r[0], r[1], r[2], r[3], r[4], idx)
        if obj: clash_proxies.append(obj)
    
    if not clash_proxies: return "proxies: []"
    
    full_config = {
        "proxies": clash_proxies,
        "proxy-groups": [{"name": "🚀 Auto Select", "type": "url-test", "url": "https://www.google.com/generate_204", "interval": 600, "timeout": 5000, "proxies": [p['name'] for p in clash_proxies]}],
        "rules": ["MATCH,🚀 Auto Select"]
    }
    return yaml.dump(full_config, allow_unicode=True, sort_keys=False)

async def handle_sub(request):
    import database_vpn as db
    # Берем ЭЛИТНУЮ подписку (VIP) по умолчанию, так как она лучше
    rows = db.get_vip_sub() 
    return web.Response(text=generate_clash_yaml(rows), content_type='text/yaml')

async def start_server():
    app = web.Application(); app.router.add_get('/sub', handle_sub)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8080).start()
