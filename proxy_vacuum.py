import asyncio
import requests
import re
import base64
import json
import time
import logging
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
TEMP_SUB_PATH = "clash_sub.yaml.tmp"
FINAL_SUB_PATH = "clash_sub.yaml"

def safe_decode(s):
    try: return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except: return ""

# --- КОНВЕРТЕР ССЫЛКИ В SING-BOX JSON ---
def link_to_singbox_outbound(link):
    try:
        if link.startswith("vmess://"):
            d = json.loads(safe_decode(link[8:]))
            out = {"type": "vmess", "tag": "proxy", "server": d['add'], "server_port": int(d['port']), "uuid": d['id'], "security": "auto"}
            if d.get('net') == 'ws': out["transport"] = {"type": "ws", "path": d.get('path', '/')}
            if d.get('tls') == 'tls': out["tls"] = {"enabled": True, "insecure": True}
            return out
        if link.startswith("vless://"):
            p = urlparse(link); q = parse_qs(p.query)
            out = {"type": "vless", "tag": "proxy", "server": p.hostname, "server_port": p.port, "uuid": p.username}
            if q.get('security', [''])[0] == 'reality':
                out["tls"] = {"enabled": True, "server_name": q.get('sni', [''])[0], "reality": {"enabled": True, "public_key": q.get('pbk', [''])[0], "short_id": q.get('sid', [''])[0]}, "utls": {"enabled": True, "fingerprint": "chrome"}}
            return out
    except: return None

# --- ТЯЖЕЛАЯ ПРОВЕРКА ЧЕРЕЗ ЯДРО ---
async def singbox_check(url, semaphore):
    async with semaphore:
        port = random.randint(20000, 30000)
        outbound = link_to_singbox_outbound(url)
        if not outbound: return None
        
        config = {
            "log": {"level": "silent"},
            "inbounds": [{"type": "mixed", "listen": "127.0.0.1", "listen_port": port}],
            "outbounds": [outbound, {"type": "direct", "tag": "direct"}]
        }
        
        cfg_file = f"cfg_{port}.json"
        with open(cfg_file, 'w') as f: json.dump(config, f)
        
        proc = subprocess.Popen([SINGBOX_BIN, "run", "-c", cfg_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.sleep(1.5) # Даем проснуться
        
        try:
            # Пробуем скачать Google 204
            start = time.time()
            # Проверка через curl (используем прокси, который поднял sing-box)
            check = await asyncio.create_subprocess_shell(
                f"curl -x socks5h://127.0.0.1:{port} -s -o /dev/null -w '%{{http_code}}' --max-time 3 http://www.google.com/generate_204",
                stdout=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(check.communicate(), timeout=4)
            lat = int((time.time() - start) * 1000)
            
            if stdout.decode().strip() == "204":
                # ВТОРОЙ ТЕСТ: Google AI Studio
                ai_check = await asyncio.create_subprocess_shell(
                    f"curl -x socks5h://127.0.0.1:{port} -s -o /dev/null -w '%{{http_code}}' --max-time 3 https://aistudio.google.com",
                    stdout=asyncio.subprocess.PIPE
                )
                ai_out, _ = await ai_check.communicate()
                is_ai = 1 if ai_out.decode().strip() in ["200", "403"] else 0
                return {"url": url, "lat": lat, "is_ai": is_ai}
        except: pass
        finally:
            proc.terminate()
            if os.path.exists(cfg_file): os.remove(cfg_file)
        return None

# --- ГЕНЕРАЦИЯ ПОЛНОГО CLASH CONFIG ---
def update_clash_file():
    import yaml
    try:
        rows = db.get_best_proxies_for_sub() # (url, lat, is_ai, country)
        from keep_alive import link_to_clash_dict # Используем твой конвертер
        
        clash_proxies = []
        for r in rows:
            obj = link_to_clash_dict(r[0], r[1], r[2], r[3])
            if obj:
                while any(p['name'] == obj['name'] for p in clash_proxies): obj['name'] += " "
                clash_proxies.append(obj)
        
        if not clash_proxies: return

        full_config = {
            "port": 7890, "socks-port": 7891, "allow-lan": True, "mode": "rule", "log-level": "info",
            "proxies": clash_proxies,
            "proxy-groups": [
                {"name": "🚀 Auto Select", "type": "url-test", "url": "http://www.gstatic.com/generate_204", "interval": 300, "proxies": [p['name'] for p in clash_proxies]},
                {"name": "🌍 Proxy", "type": "select", "proxies": ["🚀 Auto Select"] + [p['name'] for p in clash_proxies]}
            ],
            "rules": ["MATCH,🌍 Proxy"]
        }
        
        # АТОМАРНАЯ ЗАПИСЬ
        with open(TEMP_SUB_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(full_config, f, allow_unicode=True, sort_keys=False)
        os.replace(TEMP_SUB_PATH, FINAL_SUB_PATH) # Мгновенная замена
        logging.info(f"💾 Подписка обновлена: {len(clash_proxies)} серверов.")
    except Exception as e: logging.error(f"Save error: {e}")

# ... (scraper_task как был) ...

async def checker_task():
    sem = asyncio.Semaphore(5) # Проверяем по 5 штук через ядро (чтобы Koyeb не упал)
    while True:
        candidates = db.get_proxies_to_check(50)
        if not candidates:
            await asyncio.sleep(10); continue
        
        results = await asyncio.gather(*(singbox_check(u, sem) for u in candidates))
        
        for i, res in enumerate(results):
            if res: db.update_proxy_status(res['url'], res['lat'], res['is_ai'], "UN")
            else: db.update_proxy_status(candidates[i], None, 0, "")
        
        update_clash_file()
        await asyncio.sleep(5)

async def vacuum_job():
    asyncio.create_task(scraper_task())
    asyncio.create_task(checker_task())
    while True: await asyncio.sleep(3600)
