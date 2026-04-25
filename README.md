# ⛪ 教会直播排班信息收集系统

## 项目结构
```
church-schedule/
├── backend/
│   ├── app.py              # Flask 后端主程序
│   └── requirements.txt    # Python 依赖
└── frontend/
    └── index.html          # H5 前端页面
```

## 技术栈
- **前端**: HTML5 + Tailwind CSS (CDN) + Vanilla JS，零构建工具
- **后端**: Python Flask + SQLite + SSE (Server-Sent Events)
- **实时同步**: SSE 实现填报结果实时推送

## 快速启动

### 1. 安装依赖
```bash
cd backend
pip install -r requirements.txt
```

### 2. 启动服务
```bash
python app.py
```
服务将在 `http://0.0.0.0:5000` 启动，直接访问即可看到 H5 页面。

### 3. 部署到服务器（生产环境）

#### 使用 Gunicorn（推荐）
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

#### 使用 Nginx 反向代理
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # SSE 支持
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
    }
}
```

## 核心功能

### 填报端（H5页面）
1. **岗位选择**: 导播、固定机位摄像(3名)、移动机位摄像(1名)、替补/机动
2. **日期可用性**: 点击日期切换 可来(绿) / 不可来(红) / 未选(灰)
3. **实时查看**: 提交后立即看到所有人填报结果
4. **自动更新**: 他人填报时自动刷新，无需手动刷新页面

### 管理端（API）
- `GET /api/sundays` - 获取当月周日列表
- `GET /api/submissions` - 获取所有填报
- `POST /api/submissions` - 创建/更新填报（按姓名去重）
- `DELETE /api/submissions/<id>` - 删除填报
- `GET /api/stream` - SSE 实时数据流
- `POST /api/config` - 更新配置（切换月份等）

## 数据模型

### submissions 表
| 字段 | 说明 |
|------|------|
| id | UUID |
| name | 姓名 |
| phone | 电话 |
| roles | JSON ["director", "fixed_camera"] |
| available_dates | JSON {"2026-05-04": true} |
| unavailable_dates | JSON ["2026-05-11"] |
| notes | 备注 |

## 切换月份

默认自动计算下个月的所有周日。如需切换到特定月份：

```bash
curl -X POST http://localhost:5000/api/config \
  -H "Content-Type: application/json" \
  -d '{"key": "current_month", "value": "2026-06"}'
```

## 注意事项

1. **SQLite 文件**: `schedule.db` 会自动生成在 backend 目录，建议定期备份
2. **SSE 兼容性**: 现代浏览器均支持，微信内置浏览器也支持
3. **并发**: 使用 threading.Lock 保证 SSE 订阅列表线程安全
4. **手机适配**: 完全响应式，针对手机触摸优化

## 扩展建议

如需更完善的功能，可以考虑：
- 添加简单的登录/密码保护（防止误删他人数据）
- 导出 Excel 功能（用 openpyxl）
- 短信/微信通知提醒未填报人员
- 排班算法（基于可用性自动排班）
