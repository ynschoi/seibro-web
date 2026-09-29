#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEIBRO 조회 클라이언트 (웹앱용)
seibro_crawler.py 의 조회 로직을 웹앱에서 재사용하기 위한 모듈.
엑셀 기록 없이, 조회 결과를 dict/list 로 반환한다.
"""

import time
import requests
import xml.etree.ElementTree as ET
from datetime import date
from dateutil.relativedelta import relativedelta

BASE_URL = 'https://seibro.or.kr'
API_URL  = f'{BASE_URL}/websquare/engine/proworks/callServletService.jsp'
SM_URL   = f'{BASE_URL}/websquare/control.jsp?w2xPath=/IPORTAL/user/moneyMarke/BIP_CNTS04003V.xml&menuNo=125'
BOND_URL = f'{BASE_URL}/websquare/control.jsp?w2xPath=/IPORTAL/user/bond/BIP_CNTS03034V.xml&menuNo=407'

DEFAULT_YEARS = {'ABSTB': 1, 'ABCP': 2, 'ABL': 1}

COL_MAP = [
    ('COL_1',   '1~10일'),
    ('COL_11',  '11~29일'),
    ('COL_30',  '30~89일'),
    ('COL_90',  '90~179일'),
    ('COL_180', '180일 ~ 1년미만'),
    ('COL_1Y',  '1년이상'),
    ('COL_SUM', '합계'),
]
SM_TYPES = ['ABCP', '단기사채']   # 일반CP 제외 (ABS SPC는 해당 없음)
SM_ROWS  = ['종목수', '금액']


def make_session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/143.0.0.0 Safari/537.36'
        )
    })
    s.get(f'{BASE_URL}/websquare/control.jsp?w2xPath=/IPORTAL/user/index.xml', timeout=30)
    s.get(SM_URL, timeout=30)
    s.get(BOND_URL, timeout=30)
    return s


def api_post(session, xml_body, submission_id, referer, retries=2):
    """SEIBRO API 호출. 간헐적 네트워크/응답 오류 시 재시도."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = session.post(
                API_URL,
                data=xml_body.encode('utf-8'),
                headers={
                    'Accept': 'application/xml',
                    'Content-Type': 'application/xml; charset="UTF-8"',
                    'submissionid': submission_id,
                    'Referer': referer,
                },
                timeout=30,
            )
            return ET.fromstring(r.text)   # 응답이 XML이 아니면(HTML 오류페이지 등) ParseError
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))   # 점증 대기 후 재시도
    raise last_err


def clean_company_name(name):
    """SPC명에서 법인격 표기((주),(유),㈜,주식회사 등) 제거 후 검색어로 사용."""
    n = name or ''
    for tok in ['㈜', '㈜', '(주)', '(유)', '(주식회사)', '(유한회사)',
                '(자)', '(사)', '(합)', '(재)', '주식회사', '유한회사', '유한책임회사']:
        n = n.replace(tok, '')
    return n.strip()


def search_company(session, name, call_type, referer):
    q = clean_company_name(name)   # (주)/(유) 등 제거한 이름으로 검색
    xml = (
        f'<reqParam action="searchCommonpopupContentList"'
        f' task="ksd.safe.bip.cmuc.User.process.SearchPTask">'
        f'<SECN_TPCD value=""/>'
        f'<search_string value="{q}"/>'
        f'<call_type value="{call_type}"/>'
        f'<pstd_dt value=""/><sf_radio1 value=""/>'
        f'<s_type value=""/><start_dt value=""/><end_dt value=""/>'
        f'</reqParam>'
    )
    root = api_post(session, xml, 'submission_searchCommonpopupContentList', referer)
    companies = [
        (d.find('.//CODE').get('value'), d.find('.//CODE_NM').get('value'))
        for d in root.findall('.//data')
        if d.find('.//CODE') is not None and d.find('.//CODE_NM') is not None
    ]
    exact = [(c, n) for c, n in companies if n == q or n == name]
    if exact:
        return exact[0]
    if companies:
        return companies[0]
    return (None, None)


def prev_business_day(d):
    """직전 영업일(주말 제외). d는 date."""
    from datetime import timedelta
    d = d - timedelta(days=1)
    while d.weekday() >= 5:   # 5=토, 6=일
        d = d - timedelta(days=1)
    return d


def _fetch_short_term(session, code, ic_start, ic_end, std_dt):
    """단일 STD_DT로 잔기별 잔액 1회 조회. dict[(구분,분류)]=items 반환."""
    xml = (
        f'<reqParam action="expiryIssuRemaCountListEL1"'
        f' task="ksd.safe.bip.cnts.MoneyMarke.process.ShortmFncegdStatPTask">'
        f'<MENU_NO value="125"/>'
        f'<CMM_BTN_ABBR_NM value="total_search,openall,print,hwp,word,pdf,searchIcon,seach,xls,xls,"/>'
        f'<W2XPATH value="/IPORTAL/user/moneyMarke/BIP_CNTS04003V.xml"/>'
        f'<ISSUCO_CUSTNO value="{code}"/>'
        f'<INDTP_CLSF_NO value=""/>'
        f'<ic_start value="{ic_start}"/>'
        f'<ic_end value="{ic_end}"/>'
        f'<STD_DT value="{std_dt}"/>'
        f'</reqParam>'
    )
    root = api_post(session, xml, 'submission_expiryIssuRemaCountListEL1', SM_URL)
    result = {}
    for d in root.findall('.//data'):
        r = d.find('.//result')
        if r is None:
            continue
        items = {child.tag: child.get('value', '') for child in r}
        key = (items.get('SECN_TPNM', ''), items.get('ROW_TP', ''))
        result[key] = items
    return result


def _has_amount(sm):
    """조회 결과에 0이 아닌 금액/종목수가 하나라도 있으면 True."""
    for (sec, row_tp), items in sm.items():
        for field, _ in COL_MAP:
            if safe_int(items.get(field)) != 0:
                return True
    return False


def get_short_term_data(session, code, ic_start, ic_end, std_dt=None, probe_back=8):
    """잔기별 잔액 조회.
    이 데이터는 '전영업일 기준 미상환잔액'이라 STD_DT를 직전 영업일로 잡아야 함.
    STD_DT 미지정 시: 직전 영업일부터 조회, 전부 0이면 주말/공휴일일 수 있으므로
    데이터가 나올 때까지 최대 probe_back 영업일 거슬러 올라감.
    반환: (sm_dict, used_std_dt)"""
    if std_dt is not None:
        return _fetch_short_term(session, code, ic_start, ic_end, std_dt), std_dt

    d = prev_business_day(date.today())
    first_std = None
    first_sm = None
    for _ in range(probe_back):
        s = d.strftime('%Y%m%d')
        sm = _fetch_short_term(session, code, ic_start, ic_end, s)
        if first_std is None:
            first_std, first_sm = s, sm   # 가장 최근 영업일(전부 0이어도 기준값)
        if _has_amount(sm):
            return sm, s
        d = prev_business_day(d)
    # 최대 probe_back 영업일 모두 0 → 실제 잔액 없음. 가장 최근 영업일 기준 반환.
    return first_sm, first_std


def get_bond_issu_rema(session, isin):
    xml = (
        f'<reqParam action="issuInfoViewEL1"'
        f' task="ksd.safe.bip.cnts.bone.process.BondSecnDetailPTask">'
        f'<ISIN value="{isin}"/>'
        f'</reqParam>'
    )
    try:
        root = api_post(session, xml, 'submission_issuInfoViewEL1', BOND_URL)
        node = root.find('.//result/ISSU_REMA')
        if node is not None:
            return node.get('value', '')
    except Exception:
        pass
    return ''


def get_bond_data(session, code, dt1='20000101', dt2=None):
    if dt2 is None:
        dt2 = date.today().strftime('%Y%m%d')
    xml = (
        f'<reqParam action="bondIssuSecnPListEL1"'
        f' task="ksd.safe.bip.cnts.bone.process.BondSecnPTask">'
        f'<STD_TYPE value="1"/>'
        f'<ISSUCO_CUSTNO value="{code}"/>'
        f'<STD_DT1 value="{dt1}"/>'
        f'<STD_DT2 value="{dt2}"/>'
        f'<START_PAGE value="1"/>'
        f'<END_PAGE value="9999"/>'
        f'<ISSU_FORM value=""/>'
        f'</reqParam>'
    )
    root = api_post(session, xml, 'submission_bondIssuSecnPListEL1', BOND_URL)
    bonds = []
    for d in root.findall('.//data'):
        r = d.find('.//result')
        if r is not None:
            bonds.append({child.tag: child.get('value', '') for child in r})
    for b in bonds:
        isin = b.get('ISIN', '')
        if isin:
            b['ISSU_REMA'] = get_bond_issu_rema(session, isin)
    return bonds


def get_monthly_expiry(session, code, ic_start, ic_end):
    """월별 만기금액 조회. [{'년월','CP','ABCP','단기사채','합계'}, ...] 반환.
    컬럼 매핑(화면 본문 순서): 년월=XPIR_YYMM, CP=FACE_AMT1, ABCP=FACE_AMT3, 단기사채=FACE_AMT2, 합계=TOT_SUM"""
    xml = (
        f'<reqParam action="mmbyXpirAmtList"'
        f' task="ksd.safe.bip.cnts.MoneyMarke.process.ShortmFncegdStatPTask">'
        f'<MENU_NO value="125"/>'
        f'<W2XPATH value="/IPORTAL/user/moneyMarke/BIP_CNTS04003V.xml"/>'
        f'<ISSUCO_CUSTNO value="{code}"/>'
        f'<INDTP_CLSF_NO value=""/>'
        f'<ic_start value="{ic_start}"/>'
        f'<ic_end value="{ic_end}"/>'
        f'</reqParam>'
    )
    root = api_post(session, xml, 'submission_mmbyXpirAmtList', SM_URL)
    rows = []
    for d in root.findall('.//data'):
        r = d.find('.//result')
        if r is None:
            continue
        it = {c.tag: c.get('value', '') for c in r}
        rows.append({
            '년월': it.get('XPIR_YYMM', ''),
            'ABCP': safe_int(it.get('FACE_AMT3_SUM')),
            '단기사채': safe_int(it.get('FACE_AMT2_SUM')),
            '합계': safe_int(it.get('TOT_SUM')),
        })
    return rows


def safe_int(v, default=0):
    try:
        return int(v) if v and str(v).strip() else default
    except Exception:
        return default


def to_ym(d):  return d.strftime('%Y%m')
def to_ymd(d): return d.strftime('%Y%m%d')


# 장기(채권) 그룹 vs 단기(단기금융) 그룹
LONG_TYPES  = ('ABS', 'ABL')       # 장기 → 채권 조회
SHORT_TYPES = ('ABSTB', 'ABCP')    # 단기 → 단기금융 조회

# 화면 기본 조회기간 (년)
DEFAULT_LONG_YEARS  = 10
DEFAULT_SHORT_YEARS = 2


def is_long(security_type):
    return security_type in LONG_TYPES


def _norm_ymd(s):
    """'2024-09-27' / '2024-09-27 00:00:00' / '20240927' → '20240927'. 빈값이면 None."""
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    digits = ''.join(ch for ch in s if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else None


def default_period(security_type):
    """(start_ymd, end_ymd) 화면 기본기간."""
    today = date.today()
    yrs = DEFAULT_LONG_YEARS if is_long(security_type) else DEFAULT_SHORT_YEARS
    return to_ymd(today - relativedelta(years=yrs)), to_ymd(today)


def calc_dates(security_type):
    """(period_start_ymd, period_end_ymd, ic_start_ym, ic_end_ym) — 하위호환용."""
    start, end = default_period(security_type)
    if is_long(security_type):
        return start, end, None, None
    return start, end, start[:6], end[:6]


# ─────────────────────────────────────────────────────────────
# 웹앱용 고수준 조회 함수
# ─────────────────────────────────────────────────────────────

def query(spc_name, security_type, start=None, end=None):
    """
    SPC명 + 증권종류로 조회.
    security_type: ABSTB / ABCP (단기) | ABS / ABL (장기)
    start, end: 'YYYY-MM-DD' 또는 'YYYYMMDD' (조회기간, 없으면 기본값)
    반환: 화면2 리스트용 요약 + 화면3/4 상세 데이터 모두 포함.
    """
    d_start, d_end = default_period(security_type)
    s_ymd = _norm_ymd(start) or d_start
    e_ymd = _norm_ymd(end) or d_end

    session = make_session()

    if is_long(security_type):
        # ── 장기(채권) ──
        code, found = search_company(session, spc_name, '4', BOND_URL)
        if not code:
            code, found = search_company(session, spc_name, '32', SM_URL)
        if not code:
            return {
                'ok': True, 'kind': 'long', 'found': False,
                'spc_name': spc_name, 'security_type': security_type,
                'period': {'start': s_ymd, 'end': e_ymd},
                'abs_balance': 0, 'abs_amount': 0, 'total': 0, 'bonds': [],
            }

        bonds = get_bond_data(session, code, s_ymd, e_ymd)
        rows = []
        for b in bonds:
            rows.append({
                '채권명': b.get('KOR_SECN_NM', ''),
                'ISIN코드': b.get('ISIN', ''),
                '발행일': b.get('ISSU_DT', ''),
                '만기일': b.get('RED_DT', ''),
                '통화코드': b.get('ISSU_CUR_CD', ''),
                '발행금액': safe_int(b.get('FIRST_ISSU_AMT')),   # 발행금액 = 발행액면금액
                '발행잔액': safe_int(b.get('ISSU_REMA')),
                '표면금리': b.get('COUPON_RATE', ''),
                '이자유형': b.get('INT_KIND', ''),
                '발행형태': b.get('ISSU_FORM', ''),
            })
        abs_balance = sum(r['발행잔액'] for r in rows)   # ABS 발행잔액(ISSU_REMA 합)
        abs_amount  = sum(r['발행금액'] for r in rows)   # ABS 발행금액(발행액면금액 합)
        return {
            'ok': True, 'kind': 'long', 'found': True,
            'spc_name': spc_name, 'security_type': security_type,
            'found_name': found, 'code': code,
            'period': {'start': s_ymd, 'end': e_ymd},
            'abs_balance': abs_balance,
            'abs_amount': abs_amount,
            'total': abs_balance,     # 총잔액 = 발행잔액
            'bonds': rows,
        }

    else:
        # ── 단기(단기금융) ──
        ic_start, ic_end = s_ymd[:6], e_ymd[:6]
        code, found = search_company(session, spc_name, '32', SM_URL)
        if not code:
            code, found = search_company(session, spc_name, '4', BOND_URL)
        if not code:
            return {
                'ok': True, 'kind': 'short', 'found': False,
                'spc_name': spc_name, 'security_type': security_type,
                'period': {'start': s_ymd, 'end': e_ymd},
                'abstb_balance': 0, 'abcp_balance': 0, 'total': 0,
                'balance_table': [], 'monthly': [],
            }

        sm, used_std = get_short_term_data(session, code, ic_start, ic_end)
        monthly = get_monthly_expiry(session, code, ic_start, ic_end)

        abstb_bal = safe_int(sm.get(('단기사채', '금액'), {}).get('COL_SUM'))  # ABSTB=단기사채
        abcp_bal  = safe_int(sm.get(('ABCP', '금액'), {}).get('COL_SUM'))

        # 만기별 발행잔액 표 (금액만, ABCP·ABSTB 순) — 화면4
        bucket_labels = [label for field, label in COL_MAP if field != 'COL_SUM']
        balance_table = []
        for disp, key in [('ABCP', 'ABCP'), ('ABSTB', '단기사채')]:
            amt = sm.get((key, '금액'), {})
            row = {'구분': disp, '총 발행잔액': safe_int(amt.get('COL_SUM'))}
            for field, label in COL_MAP:
                if field == 'COL_SUM':
                    continue
                row[label] = safe_int(amt.get(field))
            balance_table.append(row)

        # 월별만기금액 (합계, ABCP, ABSTB) — 화면4
        monthly_out = [{
            '년월': m['년월'], '합계': m['합계'],
            'ABCP': m['ABCP'], 'ABSTB': m['단기사채'],
        } for m in monthly]

        return {
            'ok': True, 'kind': 'short', 'found': True,
            'spc_name': spc_name, 'security_type': security_type,
            'found_name': found, 'code': code,
            'period': {'start': s_ymd, 'end': e_ymd},
            'std_dt': used_std,
            'abstb_balance': abstb_bal,
            'abcp_balance': abcp_bal,
            'total': abstb_bal + abcp_bal,
            'bucket_labels': bucket_labels,
            'balance_table': balance_table,
            'monthly': monthly_out,
        }
