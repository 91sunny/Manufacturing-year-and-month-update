"""
ezadmin 바코드 양식 제조연월 자동 업데이트 스크립트
"""
import json, datetime, logging, sys, os, calendar, re, requests

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
def load_config():
    if not os.path.exists(CONFIG_FILE):
        print("config.json 없음"); sys.exit(1)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)

cfg = load_config()
EZADMIN_URL  = cfg.get("EZADMIN_URL", "https://ga25.ezadmin.co.kr")
LOGIN_DOMAIN = cfg["LOGIN_DOMAIN"]
LOGIN_ID     = cfg["LOGIN_ID"]
LOGIN_PW     = cfg["LOGIN_PW"]
SWITCH_WEEK  = cfg.get("SWITCH_WEEK", "last")
RSA_N = cfg.get("RSA_N","80863e5e41076dbff1e46891a0eed30bff4a87528e6841088245585455d5bbcfaa2f16e7f8a46f0e3624deeab2d2e9fbf0f981feb77749a739542712db60708f6f870282259f5fa6d2252e6c00cbc36d95cf94710a0d456641edfd60cfd53e5d6a3ebc5ef943ce8aed0b5f39dc58bba0da677f5dfc97950dded75334714661c5")
RSA_E = cfg.get("RSA_E","010001")

TARGET_TEMPLATES = cfg.get("TARGET_TEMPLATES", {
    "가격택 잡화(가죽제품) -오중":        "10149",
    "가격택 (의류 -가죽제품) -오중":      "10147",
    "가격택 슈즈 (가죽제품)":            "10087",
    "가격택 슈즈 (가죽제품) -오중":       "10144",
    "가격택 슈즈 (면,폴리) -오중":        "10145",
    "가격택 슈즈 (폴리,면)":            "10088",
    "가격택 슈즈 (폴리,면) 혼용률 3줄":   "10135",
    "가격택 잡화 (3줄)":               "10100",
    "가격택 잡화 (가죽제품)":           "10090",
    "가격택 잡화 -오중":               "10148",
    "가격택 텐트":                    "10092",
    "케어라벨 (가죽제품)":             "10096",
    "케어라벨 (니콜_대한민국)":         "10104",
    "케어라벨 (니콜_중국)":            "10124",
    "케어라벨 (잡화)":                "10095",
    "가격택 (의류) -NEW":             "10153",
    "가격택 (의류) -NEW_오중":         "10156",
    "가격택 (의류) 작은사이즈 NEW":     "10161",
    "가격택 슈즈 (가죽제품) -오중 NEW": "10157",
    "가격택 슈즈 (면,폴리) -오중 NEW":  "10162",
    "가격택 잡화 -오중 NEW":           "10159",
    "가격택 잡화(가죽제품) -오중 NEW":  "10160",
})

log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"update_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

def get_week_of_month(d):
    first_weekday = d.replace(day=1).weekday()
    return (d.day + first_weekday - 1) // 7 + 1

def get_total_weeks(year, month):
    last = datetime.date(year, month, calendar.monthrange(year, month)[1])
    return get_week_of_month(last)

def calc_mfg_date(d=None):
    d = d or datetime.date.today()
    y, m = d.year, d.month
    total = get_total_weeks(y, m)
    # 3주차부터 다음 달로 전환 (config에서 override 가능)
    switch = 3 if SWITCH_WEEK == "3rd" else (total if SWITCH_WEEK == "last" else total - 1)
    if get_week_of_month(d) >= switch:
        m += 1
        if m > 12: y += 1; m = 1
    return f"{y}년 {m}월"

def rsa_encrypt(plaintext):
    try:
        from Crypto.PublicKey import RSA; from Crypto.Cipher import PKCS1_v1_5
    except ImportError:
        import subprocess
        subprocess.run([sys.executable,"-m","pip","install","pycryptodome"],check=True)
        from Crypto.PublicKey import RSA; from Crypto.Cipher import PKCS1_v1_5
    key = RSA.construct((int(RSA_N,16), int(RSA_E,16)))
    return PKCS1_v1_5.new(key).encrypt(plaintext.encode()).hex()

def login():
    s = requests.Session()
    s.headers.update({"User-Agent":"Mozilla/5.0","Referer":f"{EZADMIN_URL}/login.htm"})
    lp = s.get(f"{EZADMIN_URL}/login.htm", timeout=15)
    m = re.search(r'name="crdate"[^>]+value="([^"]+)"', lp.text)
    crdate = m.group(1) if m else datetime.date.today().strftime("%Y-%m-%d")
    encpar = rsa_encrypt(f"domain={LOGIN_DOMAIN}&userid={LOGIN_ID}&passwd={LOGIN_PW}&crdate={crdate}&encpar=")
    resp = s.post(f"{EZADMIN_URL}/login_process.php",
        data={"domain":LOGIN_DOMAIN,"userid":LOGIN_ID,"passwd":LOGIN_PW,"crdate":crdate,"encpar":encpar},
        timeout=15, allow_redirects=False)
    if resp.status_code == 302:
        loc = resp.headers.get("Location","")
        url = f"{EZADMIN_URL}/{loc.lstrip('/')}" if not loc.startswith("http") else loc
        log.info(f"로그인 성공 → {url}"); s.get(url, timeout=15); return s
    m2 = re.search(r"alert\('([^']+)'\)", resp.text)
    log.error(f"로그인 실패: {m2.group(1) if m2 else resp.text[:80]}"); return None

def call_api(session, action, data):
    data.update({"template":"S500","action":action})
    return session.post(f"{EZADMIN_URL}/function.htm", data=data, timeout=15,
        headers={"Referer":f"{EZADMIN_URL}/index.htm"}).text

def main():
    today = datetime.date.today()
    new_date = calc_mfg_date(today)
    log.info("="*60)
    log.info(f"제조연월 업데이트 | 오늘: {today} → {new_date}")
    log.info(f"양식 수: {len(TARGET_TEMPLATES)}개")
    log.info("="*60)
    session = login()
    if not session: sys.exit(1)
    mfg_re = re.compile(r'^\d{4}년\s*\d{1,2}월$')
    ok = fail = 0
    for name, no in TARGET_TEMPLATES.items():
        log.info(f"처리: [{name}]")
        try:
            rows = json.loads(call_api(session,"grid_detail",{"barcode_template":no,"_search":"false","rows":"100","page":"1","sidx":"","sord":"asc"})).get("rows",[])
            if not rows: log.warning("  항목 없음"); fail+=1; continue
            updated=False; items=[]
            for row in rows:
                cell=row.get("cell",{})
                if isinstance(cell,dict):
                    item={k:str(cell.get(k,"")) if k in("idx","pos_x","pos_y","width","height","font_size") else cell.get(k,"") for k in("idx","type","name","value","etc_value","pos_x","pos_y","width","height","font","font_weight","font_size","font_color","back_color","align")}
                    item["template"]=no
                elif isinstance(cell,list):
                    keys=("idx","type","name","value","etc_value","pos_x","pos_y","width","height","font","font_weight","font_size","font_color","back_color","align")
                    item={k:str(cell[i]) if k in("idx","pos_x","pos_y","width","height","font_size") else cell[i] for i,k in enumerate(keys)}
                    item["template"]=no
                else: continue
                etc=str(item.get("etc_value","")).strip()
                if item.get("value")=="etc" and mfg_re.match(etc):
                    log.info(f"  '{etc}' → '{new_date}'"); item["etc_value"]=new_date; updated=True
                items.append(item)
            if not updated: log.warning("  제조연월 없음"); fail+=1; continue
            log.info(f"  저장: {call_api(session,'update_detail_all',{'json':json.dumps(items,ensure_ascii=False)})[:60]}")
            ok+=1
        except Exception as e:
            log.error(f"  오류: {e}"); fail+=1
    log.info(f"완료! 성공:{ok} 실패:{fail}")
    if fail>0: sys.exit(1)

if __name__=="__main__":
    main()
