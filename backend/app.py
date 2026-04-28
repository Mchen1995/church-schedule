#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
教会直播排班信息收集系统 - 后端
技术栈: Flask + SQLite + SSE
"""

import json
import sqlite3
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
import threading

app = Flask(__name__)
CORS(app)

DATABASE = 'schedule.db'

# ==================== 固定配置 ====================
MEMBER_NAMES = [
    "白老师", "陈每文", "采莲", "海妹", "嘉玲", "丁主任",
    "屿璠", "永乐", "明壹", "永元", "康磊", "林莹",
    "赛鸿", "嘉河", "淦琴", "禹豪"
]

MEMBER_ROLES = {
    "白老师": ["director", "fixed_camera", "mobile_camera"],
    "陈每文": ["director", "fixed_camera", "mobile_camera"],
    "采莲": ["director", "fixed_camera", "mobile_camera"],
    "海妹": ["director", "fixed_camera", "mobile_camera"],
    "嘉玲": ["director", "fixed_camera", "mobile_camera"],
    "丁主任": ["fixed_camera"],
    "屿璠": ["director", "fixed_camera", "mobile_camera"],
    "永乐": ["fixed_camera", "mobile_camera"],
    "明壹": ["director", "fixed_camera", "mobile_camera"],
    "永元": ["fixed_camera"],
    "康磊": ["director", "fixed_camera", "mobile_camera"],
    "林莹": ["fixed_camera", "mobile_camera"],
    "赛鸿": ["fixed_camera", "mobile_camera"],
    "嘉河": ["director", "fixed_camera", "mobile_camera"],
    "淦琴": ["fixed_camera"],
    "禹豪": ["fixed_camera"],
}

ROLE_LABELS = {
    "director": "导播",
    "fixed_camera": "固定机位",
    "mobile_camera": "移动机位",
    "backup": "替补"
}

EXPERIENCE = {
    "白老师": "high", "陈每文": "high", "采莲": "medium", "海妹": "high",
    "嘉玲": "high", "丁主任": "medium", "屿璠": "high", "永乐": "medium",
    "明壹": "high", "永元": "low", "康磊": "medium", "林莹": "low",
    "赛鸿": "low", "嘉河": "medium", "淦琴": "low", "禹豪": "low"
}

ROSTER_NEEDS = {
    "director": 1,
    "mobile_camera": 1,
    "fixed_camera": 3
}

# 默认排班日期（首次初始化时写入数据库）
DEFAULT_SCHEDULE_DATES = [
    {"date": "2026-05-02", "note": ""},
    {"date": "2026-05-09", "note": "圣餐"},
    {"date": "2026-05-16", "note": ""},
    {"date": "2026-05-23", "note": ""},
    {"date": "2026-05-30", "note": ""},
]


# ==================== 数据库初始化 ====================
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS submissions ("
        "id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, phone TEXT, "
        "availability TEXT NOT NULL, notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS config "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    # 🆕 场次表：支持动态增删，带备注字段
    c.execute(
        "CREATE TABLE IF NOT EXISTS schedule_dates ("
        "id TEXT PRIMARY KEY, date TEXT NOT NULL UNIQUE, "
        "note TEXT DEFAULT '', sort_order INTEGER NOT NULL, "
        "created_at TEXT NOT NULL)"
    )

    # 如果场次表为空，写入默认数据
    c.execute("SELECT COUNT(*) FROM schedule_dates")
    if c.fetchone()[0] == 0:
        now = datetime.now().isoformat()
        for idx, item in enumerate(DEFAULT_SCHEDULE_DATES):
            c.execute(
                "INSERT INTO schedule_dates (id, date, note, sort_order, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), item["date"], item["note"], idx, now)
            )

    conn.commit()
    conn.close()


# ==================== 工具函数 ====================
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def get_schedule_dates():
    """从数据库获取排班日期列表（按 sort_order 排序）"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, date, note FROM schedule_dates ORDER BY sort_order ASC, date ASC")
    rows = c.fetchall()
    conn.close()
    return [{"id": r["id"], "date": r["date"], "note": r["note"]} for r in rows]


def get_schedule_date_strings():
    """只返回日期字符串列表，供排班算法使用"""
    return [item["date"] for item in get_schedule_dates()]


# ==================== SSE 订阅管理 ====================
subscribers = []
subscribers_lock = threading.Lock()


def notify_subscribers(data):
    dead_subscribers = []
    with subscribers_lock:
        for q in subscribers:
            try:
                q.put(data)
            except:
                dead_subscribers.append(q)
        for q in dead_subscribers:
            if q in subscribers:
                subscribers.remove(q)


# ==================== 排班算法 ====================
def generate_roster():
    """AI推荐排班算法"""
    import random
    import copy

    SCHEDULE_DATES = get_schedule_date_strings()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM submissions")
    rows = c.fetchall()
    conn.close()

    if not rows:
        return None

    people = {}
    for row in rows:
        name = row['name']
        avail = json.loads(row['availability'])
        roles = MEMBER_ROLES.get(name, [])
        exp = EXPERIENCE.get(name, 'low')
        people[name] = {
            'availability': avail,
            'roles': roles,
            'experience': exp,
            'role_count': {r: 0 for r in roles}
        }

    best_roster = None
    best_score = float('inf')

    for attempt in range(50):
        roster = {}
        people_copy = copy.deepcopy(people)
        total_score = 0

        for date in SCHEDULE_DATES:
            roster[date] = {'director': None, 'mobile_camera': None, 'fixed_camera': []}
            role_order = ['director', 'mobile_camera', 'fixed_camera']

            for role in role_order:
                needed = ROSTER_NEEDS[role]
                candidates = []
                for name, info in people_copy.items():
                    if role not in info['roles']:
                        continue
                    status = info['availability'].get(date, 'maybe')
                    if status == 'no':
                        continue
                    score = 0
                    if status == 'yes':
                        score += 0
                    else:
                        score += 100
                    total_count = sum(info['role_count'].values())
                    score += total_count * 10
                    score += info['role_count'][role] * 25
                    if len(info['roles']) >= 2:
                        other_roles = [r for r in info['roles'] if r != role]
                        if other_roles:
                            avg_other = sum(info['role_count'][r] for r in other_roles) / len(other_roles)
                            if avg_other > info['role_count'][role]:
                                score -= 20
                    exp_score_map = {'high': 0, 'medium': 3, 'low': 8}
                    score += exp_score_map.get(info['experience'], 8)
                    if role == 'director':
                        score -= 30
                        if info['experience'] == 'high':
                            score -= 15
                        elif info['experience'] == 'medium':
                            score -= 8
                    score += random.uniform(0, 5)
                    candidates.append({'name': name, 'score': score, 'experience': info['experience']})

                candidates.sort(key=lambda x: x['score'])
                selected = []
                for candidate in candidates:
                    if len(selected) >= needed:
                        break
                    name = candidate['name']
                    exp = candidate['experience']
                    if exp == 'low':
                        current_low_count = 0
                        for n in selected:
                            if people_copy[n]['experience'] == 'low':
                                current_low_count += 1
                        for other_role, other_selected in roster[date].items():
                            if other_role == role:
                                continue
                            if isinstance(other_selected, list):
                                for n in other_selected:
                                    if people_copy.get(n, {}).get('experience') == 'low':
                                        current_low_count += 1
                            elif other_selected and people_copy.get(other_selected, {}).get('experience') == 'low':
                                current_low_count += 1
                        if current_low_count >= 2:
                            continue
                    already_assigned = False
                    for other_role, other_selected in roster[date].items():
                        if other_role == role:
                            continue
                        if isinstance(other_selected, list):
                            if name in other_selected:
                                already_assigned = True
                                break
                        elif other_selected == name:
                            already_assigned = True
                            break
                    if already_assigned:
                        continue
                    selected.append(name)
                    people_copy[name]['role_count'][role] += 1

                if role == 'fixed_camera':
                    roster[date]['fixed_camera'] = selected
                else:
                    roster[date][role] = selected[0] if selected else None

            director = roster[date].get('director')
            if director:
                exp_penalty = {'high': 0, 'medium': 5, 'low': 15}
                total_score += exp_penalty.get(people_copy[director]['experience'], 15)
                if people_copy[director]['availability'].get(date) == 'maybe':
                    total_score += 50
            else:
                total_score += 500
            mobile = roster[date].get('mobile_camera')
            if mobile:
                exp_penalty = {'high': 0, 'medium': 5, 'low': 15}
                total_score += exp_penalty.get(people_copy[mobile]['experience'], 15)
                if people_copy[mobile]['availability'].get(date) == 'maybe':
                    total_score += 50
            else:
                total_score += 300
            for person in roster[date]['fixed_camera']:
                exp_penalty = {'high': 0, 'medium': 5, 'low': 15}
                total_score += exp_penalty.get(people_copy[person]['experience'], 15)
                if people_copy[person]['availability'].get(date) == 'maybe':
                    total_score += 50
            if len(roster[date]['fixed_camera']) < 3:
                total_score += (3 - len(roster[date]['fixed_camera'])) * 150

        for name, info in people_copy.items():
            role_counts = list(info['role_count'].values())
            if len(role_counts) >= 2:
                total_score += (max(role_counts) - min(role_counts)) * 20

        if total_score < best_score:
            best_score = total_score
            best_roster = roster

    return best_roster


# ==================== API 路由 ====================

@app.route('/')
def index():
    return send_from_directory('../frontend', 'index.html')


@app.route('/api/config')
def get_config():
    """获取系统配置：人员名单、岗位映射、排班日期（含备注）"""
    schedule_dates = get_schedule_dates()
    return jsonify({
        'success': True,
        'memberNames': MEMBER_NAMES,
        'memberRoles': MEMBER_ROLES,
        'roleLabels': ROLE_LABELS,
        'scheduleDates': [item["date"] for item in schedule_dates],
        'scheduleDatesFull': schedule_dates,   # 🆕 含 id + note
        'month': '2026-05'
    })


# ==================== 🆕 场次管理 API ====================

@app.route('/api/schedule-dates', methods=['GET'])
def list_schedule_dates():
    """获取所有场次"""
    return jsonify({'success': True, 'scheduleDates': get_schedule_dates()})


@app.route('/api/schedule-dates', methods=['POST'])
def add_schedule_date():
    """新增一个场次"""
    data = request.get_json()
    date_str = (data.get('date') or '').strip()
    note = (data.get('note') or '').strip()

    if not date_str:
        return jsonify({'success': False, 'error': '日期不能为空'}), 400

    # 简单格式校验 YYYY-MM-DD
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'success': False, 'error': '日期格式错误，请使用 YYYY-MM-DD'}), 400

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM schedule_dates WHERE date = ?", (date_str,))
    if c.fetchone():
        conn.close()
        return jsonify({'success': False, 'error': '该日期已存在'}), 409

    c.execute("SELECT MAX(sort_order) FROM schedule_dates")
    row = c.fetchone()
    next_order = (row[0] or 0) + 1

    new_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    c.execute(
        "INSERT INTO schedule_dates (id, date, note, sort_order, created_at) VALUES (?, ?, ?, ?, ?)",
        (new_id, date_str, note, next_order, now)
    )
    conn.commit()
    conn.close()

    notify_subscribers({'type': 'schedule_dates_changed'})
    return jsonify({'success': True, 'id': new_id, 'date': date_str, 'note': note})


@app.route('/api/schedule-dates/<date_id>', methods=['DELETE'])
def delete_schedule_date(date_id):
    """删除一个场次"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM schedule_dates")
    total = c.fetchone()[0]
    if total <= 1:
        conn.close()
        return jsonify({'success': False, 'error': '至少保留一个场次'}), 400

    c.execute("DELETE FROM schedule_dates WHERE id = ?", (date_id,))
    conn.commit()
    deleted = c.rowcount
    conn.close()

    if not deleted:
        return jsonify({'success': False, 'error': '场次不存在'}), 404

    notify_subscribers({'type': 'schedule_dates_changed'})
    return jsonify({'success': True})


@app.route('/api/schedule-dates/<date_id>', methods=['PATCH'])
def update_schedule_date(date_id):
    """更新场次备注"""
    data = request.get_json()
    note = (data.get('note') or '').strip()

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE schedule_dates SET note = ? WHERE id = ?", (note, date_id))
    conn.commit()
    updated = c.rowcount
    conn.close()

    if not updated:
        return jsonify({'success': False, 'error': '场次不存在'}), 404

    notify_subscribers({'type': 'schedule_dates_changed'})
    return jsonify({'success': True})


# ==================== 原有提交 API ====================

@app.route('/api/submissions', methods=['GET'])
def get_submissions():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM submissions ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()

    submissions = []
    for row in rows:
        submissions.append({
            'id': row['id'],
            'name': row['name'],
            'phone': row['phone'],
            'roles': MEMBER_ROLES.get(row['name'], ["backup"]),
            'availability': json.loads(row['availability']),
            'notes': row['notes'],
            'createdAt': row['created_at'],
            'updatedAt': row['updated_at']
        })

    return jsonify({'success': True, 'submissions': submissions})


@app.route('/api/submissions', methods=['POST'])
def create_submission():
    data = request.get_json()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'error': '请选择或填写姓名'}), 400

    availability = data.get('availability', {})
    if not availability:
        return jsonify({'success': False, 'error': '请填写至少一个日期的可用性'}), 400

    current_dates = get_schedule_date_strings()
    for date in availability:
        if date not in current_dates:
            return jsonify({'success': False, 'error': f'无效的日期: {date}'}), 400
        if availability[date] not in ['yes', 'maybe', 'no']:
            return jsonify({'success': False, 'error': f'日期 {date} 的状态无效'}), 400

    submission_id = data.get('id') or str(uuid.uuid4())
    now = datetime.now().isoformat()

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM submissions WHERE name = ?", (name,))
    existing = c.fetchone()

    if existing:
        c.execute(
            "UPDATE submissions SET phone = ?, availability = ?, notes = ?, updated_at = ? WHERE id = ?",
            (data.get('phone', ''), json.dumps(availability), data.get('notes', ''), now, existing['id'])
        )
        submission_id = existing['id']
    else:
        c.execute(
            "INSERT INTO submissions (id, name, phone, availability, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (submission_id, name, data.get('phone', ''), json.dumps(availability),
             data.get('notes', ''), now, now)
        )

    conn.commit()
    conn.close()

    notify_subscribers({'type': 'update', 'submissionId': submission_id})
    return jsonify({
        'success': True,
        'id': submission_id,
        'message': '填报成功' if not existing else '更新成功'
    })


@app.route('/api/submissions/<submission_id>', methods=['DELETE'])
def delete_submission(submission_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
    conn.commit()
    deleted = c.rowcount
    conn.close()

    if deleted:
        notify_subscribers({'type': 'delete', 'submissionId': submission_id})
        return jsonify({'success': True, 'message': '删除成功'})
    else:
        return jsonify({'success': False, 'error': '记录不存在'}), 404


@app.route('/api/roster', methods=['POST'])
def get_roster():
    roster = generate_roster()
    if roster is None:
        return jsonify({'success': False, 'error': '暂无人填报，无法排班'}), 400

    schedule_dates_full = get_schedule_dates()
    note_map = {item["date"]: item["note"] for item in schedule_dates_full}

    result = {}
    for date, roles in roster.items():
        d = datetime.strptime(date, '%Y-%m-%d')
        result[date] = {
            'dateStr': f"{d.month}月{d.day}日",
            'note': note_map.get(date, ''),
            'director': roles['director'],
            'mobileCamera': roles['mobile_camera'],
            'fixedCamera': roles['fixed_camera']
        }

    return jsonify({'success': True, 'roster': result})


@app.route('/api/stream')
def stream():
    import queue
    q = queue.Queue()

    with subscribers_lock:
        subscribers.append(q)

    def generate():
        try:
            while True:
                data = q.get(timeout=30)
                yield f"data: {json.dumps(data)}\n\n"
        except queue.Empty:
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            with subscribers_lock:
                if q in subscribers:
                    subscribers.remove(q)

    return Response(generate(), mimetype='text/event-stream')


# ==================== 启动 ====================
if __name__ == '__main__':
    import sys

    port = 80
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"用法: python3 app.py [端口]")
            sys.exit(1)

    init_db()
    print(f"数据库初始化完成")
    print(f"服务启动于 http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True)