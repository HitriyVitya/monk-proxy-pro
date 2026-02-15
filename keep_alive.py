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

def is_valid_sid(s):
    """Строгая проверка Reality Short ID: не пустой, только HEX, длина 2, 4, 8 или 16"""
    if not s: return False
    s = str(s).strip()
    # Clash ждет только определенные длины short-id
    if len(s) not in [2, 4, 6, 8, 10, 12, 14, 16]: return False
    return bool(re.match(r'^[0-9a-fA-F]+$', s))

def is_valid_port(p):
    try:
        val = int(p)
        return 1 <= val <= 65535
    except: return False

def link_to_clash_dict(url, latency, tier, country, source, idx):
    try:
        flag = get_flag(country)
        tier_icon = "🥇" if tier == 1 else "🥈" if tier == 2 else "🥉"
        pc_mark = "💻" if source == 'pc' else ""
        proto_raw = url.split("://")[0].upper()
        
        name = f"{tier_icon} {flag}{pc_mark} {latency}ms | {proto_raw} (#{idx})"

        # 1. VMESS
        if url.startswith("vmess://"):
            d_str = safe_decode(url[8:])
            if not d_str: return None
            d = json.loads(d_str)
            if not is_valid_port(d.get('port')): return None
            return {
                'name': name, 'type': 'vmess', 'server': d.get('add'),
                'port': int(d.get('port')), 'uuid': d.get('id'), 'alterId': 0,
                'cipher': 'auto', 'udp': True, 'tls': d.get('tls') == 'tls',
                'skip-cert-verify': True, 'network': d.get('net', 'tcp'),
                'ws-opts': {'path': d.get('path', '/'), 'headers': {'Host': d.get('host', '')}} if d.get('net') == 'ws' else None
            }
        
        # 2. VLESS / TROJAN
        if url.startswith(("vless://", "trojan://")):
            p = urlparse(url)
            q = {k: v[0] for k, v in parse_qs(p.query).items()}
            tp = 'vless' if url.startswith('vless') else 'trojan'
            
            if not p.hostname or not is_valid_port(p.port): return None
            
            pwd_uuid = p.username or p.password
            if not pwd_uuid: return None
            
            obj = {
                'name': name, 'type': tp, 'server': p.hostname, 'port': int(p.port),
                'udp': True, 'skip-cert-verify': True, 'network': q.get('type', 'tcp')
            }
            
            if tp == 'vless': obj['uuid'] = pwd_uuid
            else: obj['password'] = pwd_uuid

            security = q.get('security', '')
            if security == 'reality':
                sid = q.get('sid', '')
                pbk = q.get('pbk', '')
                # ЖЕСТКИЙ ФИЛЬТР: если Reality, но SID кривой или пустой — В ПОМОЙКУ
                if not pbk or not is_valid_sid(sid):
                    return None
                
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
            
        # 3. SHADOWSOCKS
        if url.startswith("ss://"):
            main = url.split("#")[0].replace("ss://", "")
            if "@" in main:
                u, s = main.split("@", 1)
                d = safe_decode(u)
                m, pw = d.split(":", 1) if ":" in d else (u.split(":", 1) if ":" in u else ("aes-256-gcm", u))
                h_p = s.split("/")[0].split("?")[0]
                if ":" not in h_p: return None
                host, port = h_p.split(":")
                if not is_valid_port(port): return None
                return {'name': name, 'type': 'ss', 'server': host, 'port': int(port), 'cipher': m, 'password': pw, 'udp': True}
    except: pass
    return None

def generate_clash_yaml(rows):
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

    groups = []
    all_names = [p['name'] for p in proxies]
    groups.append({
        "name": "🚀 Auto Select",
        "type": "url-test",
        "url": "https://www.google.com/generate_204",
        "interval": 600,
        "timeout": 5000,
        "proxies": all_names
    })

    if t1_names: groups.append({"name": "🥇 Tier 1 - Stealth", "type": "select", "proxies": t1_names})
    if t2_names: groups.append({"name": "🥈 Tier 2 - Workhorse", "type": "select", "proxies": t2_names})
    if t3_names: groups.append({"name": "🥉 Tier 3 - Legacy", "type": "select", "proxies": t3_names})

    global_list = ["🚀 Auto Select"]
    if t1_names: global_list.append("🥇 Tier 1 - Stealth")
    if t2_names: global_list.append("🥈 Tier 2 - Workhorse")
    if t3_names: global_list.append("🥉 Tier 3 - Legacy")

    groups.append({"name": "🌍 GLOBAL", "type": "select", "proxies": global_list})

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
    app = web.Application()
    app.router.add_get('/sub', handle_sub)
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8080).start()
