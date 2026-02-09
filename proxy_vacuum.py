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




MAX_PAGES_TG = 20 # Глубина поиска

SINGBOX_BIN = "./sing-box"
FINAL_SUB_PATH = "clash_sub.yaml"

def safe_decode(s):
    try:
        s = re.sub(r'[^a-zA-Z0-9+/=]', '', s)
        return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except: return ""

# --- КОНВЕРТЕР ---
def link_to_singbox_json(link, local_port):
    try:
        outbound = None
        if link.startswith("vmess://"):
            d = json.loads(safe_decode(link[8:]))
            outbound = {"type": "vmess", "tag": "p", "server": d['add'], "server_port": int(d['port']), "uuid": d['id'], "security": "auto"}
            if d.get('net') == 'ws': outbound["transport"] = {"type": "ws", "path": d.get('path', '/')}
            if d.get('tls') == 'tls': outbound["tls"] = {"enabled": True, "insecure": True}
        elif link.startswith("vless://"):
            p = urlparse(link); q = parse_qs(p.query)
            outbound = {"type": "vless", "tag": "p", "server": p.hostname, "server_port": p.port, "uuid": p.username}
            sec = q.get('security', [''])[0]
            if sec == 'reality':
                outbound["tls"] = {"enabled": True, "server_name": q.get('sni', [''])[0], "reality": {"enabled": True, "public_key": q.get('pbk', [''])[0], "short_id": q.get('sid', [''])[0]}, "utls": {"enabled": True, "fingerprint": "chrome"}}
            elif sec == 'tls':
                outbound["tls"] = {"enabled": True, "server_name": q.get('sni', [''])[0], "insecure": True}
        elif link.startswith("ss://"):
            main = link.split("#")[0].replace("ss://", "")
            if "@" in main:
                u, s = main.split("@", 1); d = safe_decode(u)
                m, pw = d.split(":", 1) if ":" in d else (u.split(":", 1) if ":" in u else ("aes-256-gcm", u))
                outbound = {"type": "shadowsocks", "tag": "p", "server": s.split(":")[0], "server_port": int(s.split(":")[1].split("/")[0]), "method": m, "password": pw}
        elif link.startswith("trojan://"):
            p = urlparse(link); q = parse_qs(p.query)
            outbound = {"type": "trojan", "tag": "p", "server": p.hostname, "server_port": p.port, "password": p.username, "tls": {"enabled": True, "server_name": q.get('sni', [''])[0], "insecure": True}}

        if not outbound: return None
        return {"log": {"level": "silent"}, "inbounds": [{"type": "mixed", "listen": "127.0.0.1", "listen_port": local_port}], "outbounds": [outbound, {"type": "direct", "tag": "direct"}]}
    except: return None

# --- ТЕСТ ЧЕРЕЗ ЯДРО ---
async def singbox_check(url, semaphore):
    async with semaphore:
        port = random.randint(30000, 40000)
        config = link_to_singbox_json(url, port)
        if not config: return None
        
        cfg_file = f"cfg_{port}.json"
        with open(cfg_file, 'w') as f: json.dump(config, f)
        
        proc = None
        try:
            proc = subprocess.Popen([SINGBOX_BIN, "run", "-c", cfg_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            await asyncio.sleep(2.5) # Увеличил задержку на старт
            
            # Пробуем Google (через прокси socks5h)
            # Добавил --insecure и --location
            check_cmd = f"curl -k -x socks5h://127.0.0.1:{port} -L -s -o /dev/null -w '%{{http_code}}' --max-time 5 http://www.google.com/generate_204"
            check = await asyncio.create_subprocess_shell(check_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, _ = await asyncio.wait_for(check.communicate(), timeout=7)
            
            res_code = stdout.decode().strip()
            if res_code == "204":
                # Тест на AI Studio
                ai_cmd = f"curl -k -x socks5h://127.0.0.1:{port} -L -s -o /dev/null -w '%{{http_code}}' --max-time 5 https://aistudio.google.com"
                ai_check = await asyncio.create_subprocess_shell(ai_cmd, stdout=asyncio.subprocess.PIPE)
                ai_out, _ = await ai_check.communicate()
                is_ai = 1 if ai_out.decode().strip() in ["200", "403"] else 0
                return {"url": url, "lat": 100, "is_ai": is_ai}
            else:
                logging.debug(f"Fail: {url[:30]} code: {res_code}")
        except Exception as e:
            logging.debug(f"Check error: {e}")
        finally:
            if proc: proc.terminate()
            if os.path.exists(cfg_file): os.remove(cfg_file)
        return None

# --- ГЕНЕРАТОР ---
def update_clash_file():
    import yaml
    try:
        from keep_alive import link_to_clash_dict
        rows = db.get_best_proxies_for_sub()
        clash_proxies = []
        for idx, r in enumerate(rows):
            obj = link_to_clash_dict(r[0], r[1], r[2], r[3])
            if obj:
                obj['name'] = f"{obj['name']} ({idx})"
                clash_proxies.append(obj)
        
        if not clash_proxies:
            logging.info("⚠️ Нет живых прокси для записи в файл.")
            return

        full_config = {
            "proxies": clash_proxies,
            "proxy-groups": [{"name": "🚀 Auto Select", "type": "url-test", "url": "http://www.gstatic.com/generate_204", "interval": 300, "proxies": [p['name'] for p in clash_proxies]}],
            "rules": ["MATCH,🚀 Auto Select"]
        }
        with open(FINAL_SUB_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(full_config, f, allow_unicode=True, sort_keys=False)
        logging.info(f"💾 ФАЙЛ ОБНОВЛЕН: {len(clash_proxies)} серверов.")
    except Exception as e:
        logging.error(f"Save error: {e}")

# --- TASKS ---
async def scraper_task():
    regex = re.compile(r'(?:vless|vmess|ss|ssr|trojan|hy2|hysteria)://[^\s<"\'\)]+')
    headers = {'User-Agent': 'Mozilla/5.0'}
    while True:
        logging.info("📥 [Scraper] Запуск...")
        for url in EXTERNAL_SUBS:
            try:
                r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=10)
                t = r.text if "://" in r.text[:50] else safe_decode(r.text)
                found = regex.findall(t)
                if found: db.save_proxy_batch([l.strip() for l in found])
            except: pass
        for ch in TG_CHANNELS:
            try:
                r = await asyncio.to_thread(requests.get, f"https://t.me/s/{ch}", headers=headers, timeout=5)
                found = regex.findall(r.text)
                if found: db.save_proxy_batch([l.strip().split('<')[0] for l in found])
            except: pass
        await asyncio.sleep(1800)

async def checker_task():
    sem = asyncio.Semaphore(3) 
    while True:
        candidates = db.get_proxies_to_check(15) # Берем по 15 штук
        if candidates:
            logging.info(f"🧪 [Checker] Проверяю {len(candidates)} шт через Sing-box...")
            results = await asyncio.gather(*(singbox_check(u, sem) for u in candidates))
            
            count_live = 0
            for i, res in enumerate(results):
                if res: 
                    db.update_proxy_status(res['url'], res['lat'], res['is_ai'], "UN")
                    count_live += 1
                else: 
                    db.update_proxy_status(candidates[i], None, 0, "")
            
            logging.info(f"✅ Результат пачки: {count_live} живых.")
            update_clash_file()
        else:
            logging.info("💤 Нет новых прокси для проверки.")
        await asyncio.sleep(5)

async def vacuum_job():
    asyncio.create_task(scraper_task())
    asyncio.create_task(checker_task())
    while True: await asyncio.sleep(3600)
