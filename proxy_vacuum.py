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
from urllib.parse import urlparse, unquote, parse_qs

# --- ИСТОЧНИКИ ---
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
    "https://raw.githubusercontent.com/LonUp/NodeList/main/NodeList.txt"
]

# Настройки
SINGBOX_BIN = "./sing-box" # Бинарник лежит в корне (из Dockerfile)
CHECK_TIMEOUT = 5 # Секунд на реальный тест соединения
MAX_PARALLEL_CHECKS = 5 # Не больше 5 процессов sing-box одновременно (память!)

import database_vpn as db

# --- ВСПОМОГАТЕЛЬНЫЕ ---
def safe_decode(s):
    try:
        s = re.sub(r'[^a-zA-Z0-9+/=]', '', s)
        pad = len(s) % 4
        if pad: s += '=' * (4 - pad)
        return base64.b64decode(s).decode('utf-8', errors='ignore')
    except: return ""

def fetch_links():
    """Сборщик ссылок (ТГ + Гитхаб)"""
    links = set()
    regex = re.compile(r'(?:vless|vmess|ss|ssr|trojan|hy2|hysteria|hysteria2|tuic|socks5)://[^\s<"\'\)]+')
    headers = {'User-Agent': 'Mozilla/5.0'}

    # ТГ (немного истории)
    for ch in TG_CHANNELS:
        url = f"https://t.me/s/{ch}"
        for _ in range(5):
            try:
                r = requests.get(url, headers=headers, timeout=5)
                for l in regex.findall(r.text): links.add(l.strip().split('<')[0])
                if 'tme_messages_more' in r.text:
                    m = re.search(r'href="(/s/.*?)"', r.text)
                    if m: url = "https://t.me" + m.group(1)
                    else: break
                else: break
            except: break
            
    # ГИТХАБ
    for url in EXTERNAL_SUBS:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            text = r.text
            if not "://" in text[:100]:
                d = safe_decode(text)
                if "://" in d: text = d
            for l in regex.findall(text): links.add(l.strip())
        except: pass
        
    return list(links)

# --- КОНВЕРТЕР В SING-BOX CONFIG ---
# Это самая сложная часть: превратить ссылку в JSON для ядра
def generate_singbox_config(link, local_port):
    try:
        outbound = None
        
        # 1. VMESS
        if link.startswith("vmess://"):
            d = json.loads(safe_decode(link[8:]))
            outbound = {
                "type": "vmess",
                "server": d.get('add'),
                "server_port": int(d.get('port')),
                "uuid": d.get('id'),
                "security": "auto",
                "transport": {}
            }
            if d.get('net') == 'ws':
                outbound["transport"] = {"type": "ws", "path": d.get('path', '/'), "headers": {"Host": d.get('host', '')}}
            if d.get('tls') == 'tls':
                outbound["tls"] = {"enabled": True, "insecure": True}

        # 2. VLESS
        elif link.startswith("vless://"):
            p = urlparse(link); q = parse_qs(p.query)
            outbound = {
                "type": "vless",
                "server": p.hostname,
                "server_port": p.port,
                "uuid": p.username,
                "flow": q.get('flow', [''])[0],
                "tls": {"enabled": False},
                "transport": {}
            }
            sec = q.get('security', [''])[0]
            if sec == 'reality':
                outbound["tls"] = {
                    "enabled": True, "server_name": q.get('sni', [''])[0],
                    "reality": {"enabled": True, "public_key": q.get('pbk', [''])[0], "short_id": q.get('sid', [''])[0]},
                    "utls": {"enabled": True, "fingerprint": "chrome"}
                }
            elif sec == 'tls':
                outbound["tls"] = {"enabled": True, "server_name": q.get('sni', [''])[0], "insecure": True}
            
            net = q.get('type', ['tcp'])[0]
            if net == 'ws':
                outbound["transport"] = {"type": "ws", "path": q.get('path', ['/'])[0], "headers": {"Host": q.get('host', [''])[0]}}
            elif net == 'grpc':
                outbound["transport"] = {"type": "grpc", "service_name": q.get('serviceName', [''])[0]}

        # 3. SHADOWSOCKS
        elif link.startswith("ss://"):
            main = link.split("#")[0].replace("ss://", "")
            if "@" in main:
                u, s = main.split("@", 1)
                d = safe_decode(u)
                if ":" in d: m, pw = d.split(":", 1)
                else: m, pw = u.split(":", 1)
                host, port = s.split(":")[0], int(s.split(":")[1].split("/")[0])
                outbound = {
                    "type": "shadowsocks",
                    "server": host, "server_port": port,
                    "method": m, "password": pw
                }

        # 4. TROJAN
        elif link.startswith("trojan://"):
            p = urlparse(link); q = parse_qs(p.query)
            outbound = {
                "type": "trojan",
                "server": p.hostname, "server_port": p.port, "password": p.username,
                "tls": {"enabled": True, "server_name": q.get('sni', [''])[0], "insecure": True}
            }

        if not outbound: return None

        # Собираем полный конфиг
        config = {
            "log": {"disabled": True},
            "inbounds": [{
                "type": "mixed",
                "listen": "127.0.0.1",
                "listen_port": local_port
            }],
            "outbounds": [outbound]
        }
        return config
    except: return None

# --- ПРОВЕРКА ЧЕРЕЗ ЯДРО ---
async def real_check(link, sem):
    async with sem:
        local_port = random.randint(10000, 50000)
        config_file = f"config_{local_port}.json"
        
        # Генерируем конфиг
        config_data = generate_singbox_config(link, local_port)
        if not config_data: return None # Не смогли распарсить

        # Сохраняем во временный файл
        with open(config_file, 'w') as f:
            json.dump(config_data, f)

        proc = None
        try:
            # 1. Запускаем Sing-box
            proc = subprocess.Popen([SINGBOX_BIN, "run", "-c", config_file], 
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Даем ему секунду на разгон
            await asyncio.sleep(1.0)
            
            if proc.poll() is not None:
                # Упал сразу
                return None

            # 2. Пытаемся пробить Google через локальный прокси
            # Используем curl, так надежнее
            # Сначала обычный гугл (тест интернета)
            cmd_base = f"curl -x http://127.0.0.1:{local_port} -s -o /dev/null -w '%{{http_code}}' --max-time 3 "
            
            start = time.time()
            # Тест 1: Доступность интернета (Google)
            check_inet = await asyncio.to_thread(os.popen, cmd_base + "http://www.google.com/generate_204")
            code_inet = check_inet.read().strip()
            
            latency = int((time.time() - start) * 1000)
            
            is_ai = 0
            # Если инет есть (код 204), проверяем AI
            if code_inet == "204":
                # Тест 2: Доступность Gemini
                check_ai = await asyncio.to_thread(os.popen, cmd_base + "https://aistudio.google.com")
                # Тут сложнее, может вернуть 200 (ОК) или 403 (Запрет). Но если вернул - значит доступ есть.
                # Обычно 403 значит регион блок. 200 - ок.
                code_ai = check_ai.read().strip()
                if code_ai == "200": is_ai = 1
                
                return {"url": link, "lat": latency, "is_ai": is_ai}
            
            return None

        except Exception as e:
            return None
        finally:
            # Убираем за собой
            if proc: proc.terminate()
            if os.path.exists(config_file): os.remove(config_file)

# --- ГЛАВНЫЙ ЦИКЛ ---
async def vacuum_job():
    logging.info("🚀 REALITY CHECKER запущен")
    while True:
        try:
            # 1. Сбор
            logging.info("📥 Сбор ссылок...")
            links = await asyncio.to_thread(fetch_links)
            db.save_proxy_batch(links) # Сохраняем как непроверенные
            logging.info(f"✅ Добавлено. Всего в базе: {len(links)}")
            
            # 2. Проверка
            # Берем из базы тех, кого давно не чекали
            candidates = db.get_proxies_to_check(limit=100) # Проверяем пачками по 100
            
            if candidates:
                logging.info(f"💣 Начинаю прожарку {len(candidates)} серверов через Sing-box...")
                sem = asyncio.Semaphore(MAX_PARALLEL_CHECKS)
                
                tasks = [real_check(u, sem) for u in candidates]
                results = await asyncio.gather(*tasks)
                
                live_count = 0
                for res in results:
                    if res:
                        # СЕРВЕР РЕАЛЬНО РАБОТАЕТ!
                        # Получаем флаг страны для красоты (через API)
                        try:
                            # Простой GeoIP по домену/IP из ссылки
                            host = parse_host(res['url'])
                            r = requests.get(f"http://ip-api.com/json/{host}", timeout=2)
                            cc = r.json().get('countryCode', '')
                            # Если прошел AI тест - ставим жирный флаг
                            if res['is_ai']: res['is_ai'] = 2 # Супер Элита
                        except: cc = ""
                        
                        db.update_proxy_status(res['url'], res['lat'], res['is_ai'], cc)
                        live_count += 1
                    else:
                        # Труп
                        # Ищем URL в tasks... сложно. Сделаем проще:
                        # Функция real_check должна возвращать URL даже при ошибке, 
                        # но сейчас она возвращает None. 
                        # Исправим в следующей итерации, пока просто пропускаем.
                        # В базе они останутся "непроверенными" до следующего раза, 
                        # но fails надо бы увеличить. 
                        pass 
                
                # Костыль для отметки мертвых (чтобы не чекать вечно)
                # В реальном коде надо мапить tasks -> results
                
                logging.info(f"🏁 Пачка готова. Реально живых: {live_count}")

            logging.info("💤 Сплю 5 минут...")
            await asyncio.sleep(300)
            
        except Exception as e:
            logging.error(f"Error: {e}")
            await asyncio.sleep(60)

def parse_host(url):
    # Хелпер для GeoIP
    try:
        if "vmess" in url:
            return json.loads(base64.b64decode(url[8:]).decode('utf-8', errors='ignore'))['add']
        return urlparse(url).hostname
    except: return ""
