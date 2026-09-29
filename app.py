#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEIBRO 조회 웹앱
- 사용자가 SPC명 / 단기·장기 / 조회기간 입력 → 결과를 화면에 표로 표시
- 모든 조회를 SQLite 로그에 기록 (관리자 페이지에서 확인)
로컬 실행:  python app.py  → http://127.0.0.1:5000
클라우드:   gunicorn app:app   (Procfile 참고)
"""

import os
import sqlite3
import datetime
from flask import Flask, request, render_template, jsonify, g

import seibro_client as sc

app = Flask(__name__)

# 로그 DB 경로 (환경변수로 override 가능 — 클라우드 영속 디스크 대응)
DB_PATH = os.environ.get('SEIBRO_DB', os.path.join(os.path.dirname(__file__), 'usage_log.db'))
# 관리자 로그 페이지 비밀번호 (환경변수로 설정 권장)
ADMIN_PW = os.environ.get('SEIBRO_ADMIN_PW', 'admin')


# ─────────────────────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────────────────────

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            ip TEXT,
            spc_name TEXT,
            security_type TEXT,
            period_start TEXT,
            period_end TEXT,
            ok INTEGER,
            result_cnt INTEGER,
            error TEXT
        )
    """)
    con.commit()
    con.close()


def log_query(ip, spc, stype, p_start, p_end, ok, cnt, error):
    db = get_db()
    db.execute(
        "INSERT INTO logs (ts, ip, spc_name, security_type, period_start, period_end, ok, result_cnt, error) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ip, spc, stype,
         p_start, p_end, 1 if ok else 0, cnt, error)
    )
    db.commit()


# ─────────────────────────────────────────────────────────────
# 라우트
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


def _default_rows():
    """화면1 기본 SPC 목록 (input Excel의 Input 시트에서 읽어옴, 없으면 하드코딩 시드)."""
    seed = [
        ('스프링밸리', 'ABSTB'), ('뉴스텔라제육차', 'ABS'),
        ('신보2024제3차유동화전문', 'ABS'), ('엘씨글로리제일차', 'ABSTB'),
        ('와이케이디에스', 'ABSTB'), ('뉴스텔라제삼차', 'ABS'),
        ('디에이치블루', 'ABS'), ('마인드유틸리티', 'ABSTB'),
        ('산업기반신보인천김포고속도로유동화전문', 'ABS'), ('엔에이치파워제이차', 'ABL'),
        ('더퍼스트화이트', 'ABS'), ('서니클러스터', 'ABSTB'),
        ('에이치와이뉴스타트제이차', 'ABS'), ('디에스동탄전지', 'ABSTB'),
        ('와이케이슈퍼제일차', 'ABSTB'), ('하이트래디션제이차', 'ABS'),
        ('신보2024제7차유동화전문', 'ABS'),
    ]
    out = []
    for name, stype in seed:
        s, e = sc.default_period(stype)
        out.append({
            'spc_name': name, 'security_type': stype,
            'kind': '장기' if sc.is_long(stype) else '단기',
            'start': f'{s[:4]}-{s[4:6]}-{s[6:8]}',
            'end':   f'{e[:4]}-{e[4:6]}-{e[6:8]}',
        })
    return out


@app.route('/defaults')
def defaults():
    return jsonify({'rows': _default_rows()})


@app.route('/query', methods=['POST'])
def do_query():
    """단일 SPC 조회 (화면2/3/4 데이터 모두 포함)."""
    spc   = (request.form.get('spc_name') or '').strip()
    stype = (request.form.get('security_type') or '').strip()
    start = (request.form.get('start') or '').strip() or None
    end   = (request.form.get('end') or '').strip() or None

    if not spc:
        return jsonify({'ok': False, 'error': 'SPC명을 입력하세요.'})
    if stype not in ('ABSTB', 'ABCP', 'ABL', 'ABS'):
        return jsonify({'ok': False, 'error': '증권종류가 올바르지 않습니다.', 'spc_name': spc})

    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    try:
        result = sc.query(spc, stype, start=start, end=end)
    except Exception as e:
        # 에러 응답에도 증권종류/SPC명을 담아야 화면에서 장기/단기 구분이 유지됨
        result = {
            'ok': False, 'error': f'조회 중 오류: {e}',
            'spc_name': spc, 'security_type': stype,
            'period': {'start': start or '', 'end': end or ''},
        }

    period = result.get('period', {})
    if result.get('ok'):
        if result.get('kind') == 'long':
            cnt = len(result.get('bonds', []))
        else:
            cnt = result.get('total', 0)
        log_query(ip, spc, stype, period.get('start', ''), period.get('end', ''),
                  result.get('found', True), cnt or 0, '' if result.get('found', True) else '미발견')
    else:
        log_query(ip, spc, stype, '', '', False, 0, result.get('error', ''))

    return jsonify(result)


@app.route('/admin')
def admin():
    if request.args.get('pw') != ADMIN_PW:
        return '접근 권한이 없습니다. ?pw=비밀번호 를 붙이세요.', 403
    db = get_db()
    rows = db.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 500").fetchall()
    return render_template('admin.html', rows=rows)


init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
