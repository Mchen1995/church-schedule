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
# 人员总名单（支持手动输入新人，但下拉框提示这些）
MEMBER_NAMES = [
    "白老师", "陈每文", "采莲", "海妹", "嘉玲", "丁主任",
    "屿璠", "永乐", "明壹", "永元", "康磊", "林莹",
    "赛鸿", "嘉河", "淦琴", "禹豪"
]

# 每个人能胜任的岗位（客观事实，后台定义）
MEMBER_ROLES = {
    "白老师":   ["director", "fixed_camera", "mobile_camera"],
    "陈每文":   ["director", "fixed_camera", "mobile_camera"],
    "采莲":     ["fixed_camera", "mobile_camera"],
    "海妹":     ["fixed_camera", "mobile_camera"],
    "嘉玲":     ["fixed_camera", "mobile_camera"],
    "丁主任":   ["director", "fixed_camera"],
    "屿璠":     ["fixed_camera", "mobile_camera"],
    "永乐":     ["fixed_camera", "mobile_camera"],
    "明壹":     ["fixed_camera", "mobile_camera"],
    "永元":     ["fixed_camera", "mobile_camera"],
    "康磊":     ["fixed_camera", "mobile_camera"],
    "林莹":     ["fixed_camera", "mobile_camera"],
    "赛鸿":     ["fixed_camera", "mobile_camera"],
    "嘉河":     ["fixed_camera", "mobile_camera"],
    "淦琴":     ["fixed_camera", "mobile_camera"],
    "禹豪":     ["fixed_camera", "mobile_camera"],
}

# 岗位显示名称
ROLE_LABELS = {
    "director": "导播",
    "fixed_camera": "固定机位",
    "mobile_camera": "移动机位",
    "backup": "替补"
}

# 排班日期（2026年5月的周六）
SCHEDULE_DATES = ["2026-05-02", "2026-05-09", "2026-05-16", "2026-05-23", "2026-05-30"]

# ==================== 数据库初始化 ====================
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, phone TEXT, availability TEXT NOT NULL, notes TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
    conn.commit()
    conn.close()

# ==================== 工具函数 ====================
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

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

# ==================== API 路由 ====================

@app.route('/')
def index():
    return send_from_directory('../frontend', 'index.html')

@app.route('/api/config')
def get_config():
    """获取系统配置：人员名单、岗位映射、排班日期"""
    return jsonify({
        'success': True,
        'memberNames': MEMBER_NAMES,
        'memberRoles': MEMBER_ROLES,
        'roleLabels': ROLE_LABELS,
        'scheduleDates': SCHEDULE_DATES,
        'month': '2026-05'
    })

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

    # 校验：所有日期必须是 SCHEDULE_DATES 中的
    for date in availability:
        if date not in SCHEDULE_DATES:
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
        c.execute("UPDATE submissions SET phone = ?, availability = ?, notes = ?, updated_at = ? WHERE id = ?",
            (data.get('phone', ''), json.dumps(availability), data.get('notes', ''), now, existing['id']))
        submission_id = existing['id']
    else:
        c.execute("INSERT INTO submissions (id, name, phone, availability, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (submission_id, name, data.get('phone', ''), json.dumps(availability), data.get('notes', ''), now, now))

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
    port = 8080
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
