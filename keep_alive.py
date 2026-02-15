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

def is_valid_hex(s):
    if not s: return True
    return bool(re.match(r'^[0-9a-fA-F]{2,16}$', s)) and len(s) % 2 == 0

def is_valid_port(p):
    try: return 1 <= int(p) <= 65535
    except: return False

def link_to_clash_dict(url, latency, tier, country, source, idx):
    try:
        flag = get_flag(country)
        tier_icon = "🥇" if tier == 1 else "🥈" if tier == 2 else "🥉"
        pc_mark = "💻" if source == 'pc' else ""
        proto = url.split("://")[0].upper()
        name = f"{tier_icon} {flag}{pc_mark} {latency}ms | {proto} #{idx}"

        if url.startswith("vmess://"):
            d_str = safe_decode(url[8:])
            if not d_str: return None
            d = json.loads(d_str)
            if not is_valid_port(d.get('port')): return None
            return {'name': name, 'type': 'vmess', 'server': d.get('add'), 'port': int(d.get('port')), 'uuid': d.get('id'), 'alterId': 0, 'cipher': 'auto', 'udp': True, 'tls': d.get('tls') == 'tls', 'skip-cert-verify': True, 'network': d.get('net', 'tcp'), 'ws-opts': {'path': d.get('path', '/')} if d.get('net') == 'ws' else None}
        
        if url.startswith(("vless://", "trojan://")):
            p = urlparse(url); q = {k: v[0] for k, v in parse_qs(p.query).items()}; tp = 'vless' if url.startswith('vless') else 'trojan'
            if not p.hostname or not is_valid_port(p.port): return None
            pwd_uuid = p.username or p.password
            if not pwd_uuid: return None
            obj = {'name': name, 'type': tp, 'server': p.hostname, 'port': int(p.port), 'udp': True, 'skip-cert-verify': True, 'network': q.get('type', 'tcp')}
            if tp == 'vless': obj['uuid'] = pwd_uuid
            else: obj['password'] = pwd_uuid
            if q.get('security') == 'reality':
                if not is_valid_hex(q.get('sid', '')): return None
                obj['tls'] = True; obj['servername'] = q.get('sni', ''); obj['reality-opts'] = {'public-key': q.get('pbk', ''), 'short-id': q.get('sid', '')}; obj['client-fingerprint'] = 'chrome'
            elif q.get('security') == 'tls' or p.port == 443:
                obj['tls'] = True; obj['servername'] = q.get('sni', p.hostname)
            if obj.get('network') == 'ws': obj['ws-opts'] = {'path': q.get('path', '/'), 'headers': {'Host': q.get('host', p.hostname)}}
            return obj
            
        if url.startswith("ss://"):
            main = url.split("#")[0].replace("ss://", ""); u, s = main.split("@", 1)
            d = safe_decode(u); m, pw = d.split(":", 1) if ":" in d else (u.split(":", 1) if ":" in u else ("aes-256-gcm", u))
            h_p = s.split("/")[0].split("?")[0]
            if ":" not in h_p: return None
            host, port = h_p.split(":"); 
            if not is_valid_port(port): return None
            return {'name': name, 'type': 'ss', 'server': host, 'port': int(port), 'cipher': m, 'password': pw, 'udp': True}
    except: pass
    return None

def generate_clash_yaml(rows):
    """Генерация конфига с группами по ТИРАМ"""
    proxies = []
    t1_names, t2_names, t3_names = [], [], []

    for idx, r in enumerate(rows):
        # r = (url, latency, tier, country, source)
        obj = link_to_clash_dict(r[0], r[1], r[2], r[3], r[4], idx)
        if obj:
            proxies.append(obj)
            if r[2] == 1: t1_names.append(obj['name'])
            elif r[2] == 2: t2_names.append(obj['name'])
            else: t3_names.append(obj['name'])
    
    if not proxies: return "proxies: []"

    # Создаем структуру групп
    groups = []
    
    # 1. Группа автовыбора (из всех вообще)
    all_names = [p['name'] for p in proxies]
    groups.append({
        "name": "🚀 Auto Select",
        "type": "url-test",
        "url": "https://www.google.com/generate_204",
        "interval": 600,
        "timeout": 5000,
        "proxies": all_names
    })

    # 2. Группы по тирам (если они не пустые)
    if t1_names:
        groups.append({"name": "🥇 Tier 1 - Stealth", "type": "select", "proxies": t1_names})
    if t2_names:
        groups.append({"name": "🥈 Tier 2 - Workhorse", "type": "select", "proxies": t2_names})
    if t3_names:
        groups.append({"name": "🥉 Tier 3 - Legacy", "type": "select", "proxies": t3_names})

    # 3. Главная группа GLOBAL
    global_proxies = ["🚀 Auto Select"]
    if t1_names: global_proxies.append("🥇 Tier 1 - Stealth")
    if t2_names: global_proxies.append("🥈 Tier 2 - Workhorse")
    if t3_names: global_proxies.append("🥉 Tier 3 - Legacy")
    
    groups.append({
        "name": "🌍 GLOBAL",
        "type": "select",
        "proxies": global_proxies
    })

    full_config = {
        "proxies": proxies,
        "proxy-groups": groups,
        "rules": ["MATCH,🌍 GLOBAL"]
    }
    
    return yaml.dump(full_config, allow_unicode=True, sort_keys=False)

async def handle_sub(request):
    import database_vpn as db
    try:
        rows = db.get_classic_sub() 
        return web.Response(text=generate_clash_yaml(rows), content_type='text/yaml')
    except Exception as e:
        return web.Response(text=f"Error: {e}", status=500)

async def start_server():
    app = web.Application(); app.router.add_get('/sub', handle_sub)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8080).start()
