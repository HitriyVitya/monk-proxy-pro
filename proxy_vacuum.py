import asyncio
import requests
import re
import base64
import json
import time
import logging
from urllib.parse import urlparse, unquote, quote
import database as db

# --- СПИСКИ ИСТОЧНИКОВ ---
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
    "https://raw.githubusercontent.com/LonUp/NodeList/main/NodeList.txt",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt"
]

# --- ФУНКЦИИ СБОРА ---
def safe_decode(s):
    try:
        s = re.sub(r'[^a-zA-Z0-9+/=]', '', s)
        padding = len(s) % 4
        if padding: s += '=' * (4 - padding)
        return base64.b64decode(s).decode('utf-8', errors='ignore')
    except: return ""

def scrape_everything():
    """Собирает ссылки отовсюду"""
    logging.info("🧹 Vacuum: Начинаю сбор ссылок...")
    links = set()
    regex = re.compile(r'(?:vless|vmess|ss|ssr|trojan|hy2|hysteria|hysteria2|tuic|socks5)://[^\s<"\'\)]+')
    headers = {'User-Agent': 'Mozilla/5.0'}

    # 1. ТЕЛЕГРАМ (Последние 20 постов, без глубокого листания, чтобы не грузить)
    for ch in TG_CHANNELS:
        try:
            r = requests.get(f"https://t.me/s/{ch}", headers=headers, timeout=5)
            found = regex.findall(r.text)
            for l in found:
                clean = l.strip().split('<')[0].split('"')[0]
                links.add(clean)
        except: pass

    # 2. ГИТХАБ
    for url in EXTERNAL_SUBS:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            text = r.text
            # Пробуем декодировать
            decoded = safe_decode(text)
            if len(decoded) > 100: text = decoded
            
            found = regex.findall(text)
            for l in found:
                clean = l.strip()
                links.add(clean)
        except: pass
    
    return list(links)

# --- ФУНКЦИИ ПРОВЕРКИ ---
def extract_ip_port(link):
    try:
        if link.startswith("vmess://"):
            data = json.loads(safe_decode(link[8:]))
            return data.get('add'), int(data.get('port'))
        p = urlparse(link)
        if link.startswith("ss://") and "@" in link:
            part = link.split("@")[-1].split("#")[0].split("/")[0]
            if ":" in part: 
                return part.split(":")[0].replace("[","").replace("]",""), int(part.split(":")[1])
        if p.hostname and p.port: return p.hostname, p.port
    except: pass
    return None, None

async def check_connectivity(ip, port):
    """
    Легкая проверка TCP.
    Если порт открыт и отвечает быстро - считаем сервер живым.
    Для бесплатного сервера это оптимально.
    """
    try:
        start = time.time()
        conn = asyncio.open_connection(ip, port)
        _, writer = await asyncio.wait_for(conn, timeout=1.5) # Тайм-аут 1.5 сек
        latency = int((time.time() - start) * 1000)
        writer.close()
        await writer.wait_closed()
        
        # Отсекаем фейки < 5мс
        if latency < 5: return None
        return latency
    except:
        return None

def get_geo_info(ip):
    # Упрощенный GeoIP (одиночный запрос, чтобы не банили батчами)
    # Можно закэшировать или использовать базу, но пока так
    return "🏳️" # Пока заглушка для скорости

# --- ГЛАВНЫЙ ЦИКЛ ---
async def start_vacuum():
    while True:
        try:
            # 1. Сбор
            all_links = scrape_everything()
            added = db.save_proxy_batch(all_links)
            logging.info(f"🧹 Vacuum: Добавлено {added} новых. Всего найдено {len(all_links)}")
            
            # 2. Проверка (Берем из базы пачку непроверенных)
            candidates = db.get_proxies_to_check(limit=100) # Проверяем по 100 штук за раз
            logging.info(f"🧪 Vacuum: Проверяю {len(candidates)} кандидатов...")
            
            tasks = []
            for link in candidates:
                ip, port = extract_ip_port(link)
                if ip and port:
                    tasks.append((link, ip, port))
                else:
                    db.update_proxy_status(link, None, 0, "") # Невалид
            
            for link, ip, port in tasks:
                lat = await check_connectivity(ip, port)
                # Тут можно добавить проверку на AI (пока рандом или заглушка)
                is_ai = 1 if lat and lat < 200 else 0 # Пример: быстрые считаем AI
                country = "" 
                
                db.update_proxy_status(link, lat, is_ai, country)
                
            logging.info("💤 Vacuum: Сплю 10 минут...")
            await asyncio.sleep(600) # Пауза 10 мин
            
        except Exception as e:
            logging.error(f"Vacuum Error: {e}")
            await asyncio.sleep(60)
