
import asyncio
import requests
import re
import base64
import json
import time
import logging
import subprocess
import os
import random
import yaml
from bs4 import BeautifulSoup
from urllib.parse import urlparse, unquote, parse_qs, quote
import database_vpn as db

# --- СПИСКИ ---
TG_CHANNELS = [
    "shadowsockskeys", "oneclickvpnkeys", "v2ray_outlineir",
    "v2ray_free_conf", "v2rayngvpn", "v2ray_free_vpn",
    "gurvpn_keys", "vmessh", "VMESS7", "VlessConfig",
    "PrivateVPNs", "nV_v2ray", "NotorVPN", "FairVpn_V2ray",
    "outline_marzban", "outline_k"
]

EXTERNAL_SUBS = [
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/normal/mix",
    "https://raw.githubusercontent.com/vfarid/v2ray-share/main/all_v2ray_configs.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/Sub1.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/LonUp/NodeList/main/NodeList.txt",
    "https://raw.githubusercontent.com/officialputuid/V2Ray-Config/main/Splitted-v2ray-config/all"
]


SINGBOX_BIN = "./sing-box"
FINAL_SUB_PATH = "clash_sub.yaml"

def safe_decode(s):
    try: return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except: return ""

def link_to_clash_dict(url, latency, is_ai, country):
    try:
        flag = "".join(chr(ord(c) + 127397) for c in country.upper()) if len(country)==2 else "🏳️"
        ai_tag = " ✨ AI" if is_ai else ""
        try: srv = url.split('@')[-1].split(':')[0].split('.')[-1]
        except: srv = "srv"
        name = f"{flag}{ai_tag} {latency}ms | {srv}"
        # Уникальность имени
        name = f"{name} ({random.randint(100,999)})"

        if url.startswith("vmess://"):
            d = json.loads(safe_decode(url[8:]))
            return {'name': name, 'type': 'vmess', 'server': d.get('add'), 'port': int(d.get('port')), 'uuid': d.get('id'), 'alterId': 0, 'cipher': 'auto', 'udp': True, 'tls': d.get('tls') == 'tls', 'skip-cert-verify': True, 'network': d.get('net', 'tcp'), 'ws-opts': {'path': d.get('path', '/')} if d.get('net') == 'ws' else None}
        
        if url.startswith(("vless://", "trojan://")):
            p = urlparse(url); q = parse_qs(p.query); tp = 'vless' if url.startswith('vless') else 'trojan'
            obj = {'name': name, 'type': tp, 'server': p.hostname, 'port': p.port, 'uuid': p.username or p.password, 'password': p.username or p.password, 'udp': True, 'skip-cert-verify': True, 'tls': q.get('security', [''])[0] in ['tls', 'reality'], 'network': q.get('type', ['tcp'])[0]}
            if tp == 'trojan' and 'uuid' in obj: del obj['uuid']
            if q.get('security', [''])[0] == 'reality':
                obj['servername'] = q.get('sni', [''])[0]
                obj['reality-opts'] = {'public-key': q.get('pbk', [''])[0], 'short-id': q.get('sid', [''])[0]}
            return obj
        
        if url.startswith("ss://"):
            main = url.split("#")[0].replace("ss://", "")
            if "@" in main:
                u, s = main.split("@", 1); d = safe_decode(u)
                m, pw = d.split(":", 1) if ":" in d else (u.split(":", 1) if ":" in u else ("aes-256-gcm", u))
                return {'name': name, 'type': 'ss', 'server': s.split(":")[0], 'port': int(s.split(":")[1].split("/")[0]), 'cipher': m, 'password': pw, 'udp': True}
    except: pass
    return None

def update_static_file():
    try:
        rows = db.get_best_proxies_for_sub()
        clash_proxies = [link_to_clash_dict(r[0], r[1], r[2], r[3]) for r in rows]
        clash_proxies = [p for p in clash_proxies if p]
        
        full_config = {
            "proxies": clash_proxies,
            "proxy-groups": [{"name": "🚀 Auto Select", "type": "url-test", "url": "http://www.gstatic.com/generate_204", "interval": 300, "proxies": [p['name'] for p in clash_proxies]}],
            "rules": ["MATCH,🚀 Auto Select"]
        }
        with open(FINAL_SUB_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(full_config, f, allow_unicode=True, sort_keys=False)
    except Exception as e: logging.error(f"Config error: {e}")

async def scraper_task():
    regex = re.compile(r'(?:vless|vmess|ss|ssr|trojan|hy2|hysteria)://[^\s<"\'\)]+')
    headers = {'User-Agent': 'Mozilla/5.0'}
    while True:
        logging.info("📥 [Scraper] Старт...")
        for url in EXTERNAL_SUBS:
            try:
                r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=10)
                text = r.text
                if not "://" in text[:50]: text = safe_decode(text)
                found = regex.findall(text)
                if found: db.save_proxy_batch([l.strip() for l in found])
            except: pass
        
        for ch in TG_CHANNELS:
            base_url = f"https://t.me/s/{ch}"
            for _ in range(10): # Пока 10 страниц, чтобы не виснуть
                try:
                    r = await asyncio.to_thread(requests.get, base_url, headers=headers, timeout=5)
                    found = regex.findall(r.text)
                    if found: db.save_proxy_batch([l.strip().split('<')[0] for l in found])
                    if 'tme_messages_more' not in r.text: break
                    match = re.search(r'href="(/s/.*?)"', r.text)
                    if match: base_url = "https://t.me" + match.group(1)
                    else: break
                except: break
        await asyncio.sleep(1800)

async def checker_task():
    while True:
        candidates = db.get_proxies_to_check(20) # Проверяем по 20 штук за раз
        if not candidates:
            await asyncio.sleep(10); continue
            
        async def verify(url):
            # ТУТ ПРОВЕРКА ПОРТА (САМАЯ БЫСТРАЯ)
            # В будущем добавим sing-box subprocess, пока заставим работать это!
            try:
                p = urlparse(url)
                if "vmess" in url: 
                    d = json.loads(safe_decode(url[8:])); host, port = d['add'], int(d['port'])
                else: host, port = p.hostname, p.port
                
                st = time.time()
                _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.5)
                lat = int((time.time() - st) * 1000)
                w.close(); await w.wait_closed()
                is_ai = 1 if "reality" in url.lower() or lat < 200 else 0
                db.update_proxy_status(url, lat, is_ai, "UN")
            except: db.update_proxy_status(url, None, 0, "")

        await asyncio.gather(*(verify(u) for u in candidates))
        update_static_file()
        await asyncio.sleep(2)

async def vacuum_job():
    asyncio.create_task(scraper_task())
    asyncio.create_task(checker_task())
    while True: await asyncio.sleep(3600)
