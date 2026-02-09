import asyncio
import requests
import re
import base64
import json
import time
import logging
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import database_vpn as db

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
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
    "https://raw.githubusercontent.com/LonUp/NodeList/main/NodeList.txt",
    "https://raw.githubusercontent.com/officialputuid/V2Ray-Config/main/Splitted-v2ray-config/all"
]

# Настройки пылесоса
MAX_PAGES_TG = 1000  # Сколько страниц истории листать назад (глубокий поиск)
MAX_LINKS_CHECK = 200 # Сколько проверять за один цикл (чтобы не забить память)

def safe_decode(s):
    try:
        s = re.sub(r'[^a-zA-Z0-9+/=]', '', s)
        padding = len(s) % 4
        if padding: s += '=' * (4 - padding)
        return base64.b64decode(s).decode('utf-8', errors='ignore')
    except: return ""

def scrape_sync():
    """Синхронная часть сбора (чтобы не вешать бота, запустим в треде)"""
    links = set()
    regex = re.compile(r'(?:vless|vmess|ss|ssr|trojan|hy2|hysteria|hysteria2|tuic|socks5)://[^\s<"\'\)]+')
    headers = {'User-Agent': 'Mozilla/5.0'}

    logging.info("🧹 Vacuum: Начинаю сбор с Гитхаба...")
    for url in EXTERNAL_SUBS:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            text = r.text
            # Пробуем декодировать
            if len(text) > 10 and not "://" in text[:50]:
                decoded = safe_decode(text)
                if decoded: text = decoded
            
            found = regex.findall(text)
            for l in found: links.add(l.strip())
        except: pass

    logging.info(f"🧹 Vacuum: Гитхаб дал {len(links)}. Иду в Телеграм (Глубокий поиск)...")
    
    for ch in TG_CHANNELS:
        url = f"https://t.me/s/{ch}"
        pages = 0
        try:
            while pages < MAX_PAGES_TG:
                r = requests.get(url, headers=headers, timeout=10)
                soup = BeautifulSoup(r.text, 'html.parser')
                msgs = soup.find_all('div', class_='tgme_widget_message_text')
                
                if not msgs: break
                
                # Собираем со страницы
                found_on_page = 0
                for m in msgs:
                    found = regex.findall(m.get_text())
                    for l in found:
                        clean = l.strip().split('<')[0].split('"')[0]
                        links.add(clean)
                        found_on_page += 1
                
                # Ищем кнопку "More" (старые посты)
                more = soup.find('a', class_='tme_messages_more')
                if more and 'href' in more.attrs:
                    url = "https://t.me" + more['href']
                    pages += 1
                    # Небольшая пауза, чтобы ТГ не забанил
                    time.sleep(0.5)
                else:
                    break
        except: pass
    
    return list(links)

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

async def check_tcp(ip, port):
    try:
        st = time.time()
        conn = asyncio.open_connection(ip, port)
        _, w = await asyncio.wait_for(conn, timeout=1.5)
        lat = int((time.time() - st) * 1000)
        w.close()
        await w.wait_closed()
        return lat
    except: return None

async def vacuum_job():
    """Фоновый процесс"""
    while True:
        try:
            # 1. Сбор (в отдельном потоке, чтобы не тормозить бота)
            # Это может занять время, так как листает ТГ
            logging.info("🧹 Vacuum: Запускаю сканер...")
            all_links = await asyncio.to_thread(scrape_sync)
            
            # Сохраняем в базу (она сама отсеет дубликаты)
            added = db.save_proxy_batch(all_links)
            logging.info(f"🧹 Vacuum: Сбор окончен. Новых: {added}. Всего в базе: {len(all_links)}")
            
            # 2. Проверка (берем пачку старых или новых непроверенных)
            # Проверяем порциями, чтобы не перегрузить сеть
            candidates = db.get_proxies_to_check(limit=MAX_LINKS_CHECK)
            
            if candidates:
                logging.info(f"🧪 Vacuum: Проверяю {len(candidates)} серверов на живучесть...")
                sem = asyncio.Semaphore(50) # 50 одновременных проверок
                
                async def verify(url):
                    async with sem:
                        ip, port = extract_ip_port(url)
                        if ip and port:
                            lat = await check_tcp(ip, port)
                            # Определяем AI (пока простая эвристика)
                            is_ai = 1 if lat and (lat < 150 or "reality" in url.lower()) else 0
                            db.update_proxy_status(url, lat, is_ai, "")
                        else:
                            db.update_proxy_status(url, None, 0, "") # Невалид

                await asyncio.gather(*(verify(u) for u in candidates))
                logging.info(f"✅ Vacuum: Пачка проверена.")
            
            # Спим час перед следующим сбором
            # Но проверку можно запускать чаще, если нужно
            logging.info("💤 Vacuum: Сплю 1 час...")
            await asyncio.sleep(3600)
            
        except Exception as e:
            logging.error(f"❌ Vacuum Error: {e}")
            await asyncio.sleep(60)
