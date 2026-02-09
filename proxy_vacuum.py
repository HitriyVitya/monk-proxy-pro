
import asyncio
import requests
import re
import base64
import json
import time
import logging
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




FINAL_SUB_PATH = "clash_sub.yaml"
MAX_PAGES_TG = 50      # Глубина поиска в ТГ
MAX_LINKS_CHECK = 100  # Сколько проверять за один проход чекера
TIMEOUT = 2          # Таймаут на ответ сервера

# --- ВСПОМОГАТЕЛЬНЫЕ ---
def safe_decode(s):
    try:
        s = re.sub(r'[^a-zA-Z0-9+/=]', '', s)
        return base64.b64decode(s + '=' * (-len(s) % 4)).decode('utf-8', errors='ignore')
    except: return ""

def extract_ip_port(link):
    """Вытаскивает хост и порт из любого типа ссылки"""
    try:
        if link.startswith("vmess://"):
            d = json.loads(safe_decode(link[8:]))
            return d.get('add'), int(d.get('port'))
        p = urlparse(link)
        if link.startswith("ss://") and "@" in link:
            part = link.split("@")[-1].split("#")[0]
            if ":" in part: 
                return part.split(":")[0].replace("[","").replace("]",""), int(part.split(":")[1])
        if p.hostname and p.port:
            return p.hostname, p.port
    except: pass
    return None, None

async def check_tcp(ip, port):
    """Честный TCP пинг"""
    try:
        st = time.time()
        conn = asyncio.open_connection(ip, port)
        _, w = await asyncio.wait_for(conn, timeout=TIMEOUT)
        lat = int((time.time() - st) * 1000)
        w.close()
        await w.wait_closed()
        if lat < 10: return None # Отсекаем мгновенные ошибки
        return lat
    except: return None

async def get_countries_batch(ips):
    """Узнает страны для пачки IP (лимит API - 100)"""
    if not ips: return {}
    res_map = {}
    try:
        unique_ips = list(set(ips))
        # Используем асинхронный запуск для requests
        r = await asyncio.to_thread(
            requests.post, 
            "http://ip-api.com/batch?fields=query,countryCode", 
            json=[{"query": i} for i in unique_ips], 
            timeout=10
        )
        for item in r.json():
            res_map[item['query']] = item.get('countryCode', 'UN')
    except Exception as e:
        logging.error(f"GeoIP Error: {e}")
    return res_map

# --- ГЕНЕРАТОР ФАЙЛА ---
def update_static_file():
    """Собирает YAML из базы и пишет на диск атомарно"""
    try:
        from keep_alive import link_to_clash_dict
        rows = db.get_best_proxies_for_sub() # (url, lat, is_ai, country)
        clash_proxies = []
        for idx, r in enumerate(rows):
            obj = link_to_clash_dict(r[0], r[1], r[2], r[3])
            if obj:
                # ГАРАНТИРУЕМ УНИКАЛЬНОСТЬ ИМЕНИ ЧЕРЕЗ ИНДЕКС
                obj['name'] = f"{obj['name']} ({idx})"
                clash_proxies.append(obj)
        
        if not clash_proxies:
            logging.warning("⚠️ Нет живых прокси для сохранения.")
            return

        full_config = {
            "proxies": clash_proxies,
            "proxy-groups": [
                {
                    "name": "🚀 Auto Select", 
                    "type": "url-test", 
                    "url": "http://www.gstatic.com/generate_204", 
                    "interval": 300, 
                    "proxies": [p['name'] for p in clash_proxies]
                }
            ],
            "rules": ["MATCH,🚀 Auto Select"]
        }
        
        # Запись во временный файл, потом замена (чтобы не было пустых чтений)
        tmp_path = FINAL_SUB_PATH + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            yaml.dump(full_config, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp_path, FINAL_SUB_PATH)
        logging.info(f"💾 Подписка обновлена: {len(clash_proxies)} серверов.")
    except Exception as e:
        logging.error(f"Update file error: {e}")

# --- ЗАДАЧИ ---

async def scraper_task():
    """Собирает новые ссылки и кладет в базу"""
    regex = re.compile(r'(?:vless|vmess|ss|ssr|trojan|hy2|hysteria)://[^\s<"\'\)]+')
    headers = {'User-Agent': 'Mozilla/5.0'}
    while True:
        logging.info("📥 [Scraper] Запуск цикла сбора...")
        
        # 1. Гитхаб
        for url in EXTERNAL_SUBS:
            try:
                r = await asyncio.to_thread(requests.get, url, headers=headers, timeout=10)
                t = r.text if "://" in r.text[:50] else safe_decode(r.text)
                found = regex.findall(t)
                if found:
                    db.save_proxy_batch([l.strip() for l in found])
            except: pass

        # 2. Телеграм
        for ch in TG_CHANNELS:
            base_url = f"https://t.me/s/{ch}"
            for _ in range(MAX_PAGES_TG):
                try:
                    r = await asyncio.to_thread(requests.get, base_url, headers=headers, timeout=5)
                    found = regex.findall(r.text)
                    if found:
                        db.save_proxy_batch([l.strip().split('<')[0] for l in found])
                    
                    if 'tme_messages_more' not in r.text: break
                    match = re.search(r'href="(/s/.*?)"', r.text)
                    if match: base_url = "https://t.me" + match.group(1)
                    else: break
                    await asyncio.sleep(0.5)
                except: break
        
        logging.info("💤 [Scraper] Сплю 30 минут.")
        await asyncio.sleep(1800)

async def checker_task():
    """Берет пачку из базы, проверяет пинг + страну и обновляет базу"""
    sem = asyncio.Semaphore(40)
    while True:
        candidates = db.get_proxies_to_check(limit=MAX_LINKS_CHECK)
        if not candidates:
            await asyncio.sleep(10)
            continue
            
        logging.info(f"🧪 [Checker] Проверяю {len(candidates)} шт...")
        
        check_results = []

        async def verify(url):
            async with sem:
                ip, port = extract_ip_port(url)
                if ip and port:
                    lat = await check_tcp(ip, port)
                    if lat:
                        check_results.append({'url': url, 'ip': ip, 'lat': lat})
                    else:
                        db.update_proxy_status(url, None, 0, "")
                else:
                    db.update_proxy_status(url, None, 0, "")

        await asyncio.gather(*(verify(u) for u in candidates))
        
        # Если есть живые - узнаем их страны пачкой
        if check_results:
            ips = [res['ip'] for res in check_results]
            geo_map = await get_countries_batch(ips)
            
            for res in check_results:
                country = geo_map.get(res['ip'], "UN")
                # Умный флаг AI для Reality
                is_ai = 1 if "reality" in res['url'].lower() or "pbk=" in res['url'].lower() or res['lat'] < 150 else 0
                db.update_proxy_status(res['url'], res['lat'], is_ai, country)
        
        # Обновляем файл сразу после проверки пачки
        update_static_file()
        await asyncio.sleep(2)

async def vacuum_job():
    """Точка входа для main.py"""
    asyncio.create_task(scraper_task())
    asyncio.create_task(checker_task())
    while True:
        await asyncio.sleep(3600)
