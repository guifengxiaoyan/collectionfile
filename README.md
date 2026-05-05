# 文件收集系统

一个基于 Flask 的文件收集系统，支持多主题管理、文件上传收集、收集者登录认证、公告栏等功能。

## 功能特性

- **首页公告栏** - 管理员可发布公告并上传附件
- **收集主题管理** - 创建、编辑、归档/恢复主题
- **收集对象管理** - 支持 Excel 批量导入收集对象
- **收集者登录** - 收集对象关联独立登录账号，收集者需登录后查看和上传
- **权限隔离** - 收集者登录后仅可见自己关联的收集对象
- **状态自动检测** - 上传状态以附件存在与否自动判定，无需手动标记
- **文件上传** - 多附件上传，支持拖拽
- **进度追踪** - 实时显示已完成/未完成状态
- **附件导出** - 一键导出所有附件
- **科技感 UI** - 深色主题，现代化界面设计

## 技术栈

- **后端**: Python 3.11 + Flask
- **数据库**: SQLite
- **前端**: HTML5 + CSS3 + Font Awesome
- **部署**: Docker

## 快速开始

### Docker 部署（推荐）

```bash
# 1. 下载部署包
git clone https://github.com/guifengxiaoyan/collectionfile.git

# 2. 进入项目目录
cd collectionfile

# 3. 启动服务
docker-compose up -d

# 4. 访问 http://服务器IP:5000

# 更新代码并重建容器
cd collectionfile
git pull
docker compose up -d --build --force-recreate
```

### 本地开发

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python app.py

# 3. 访问 http://localhost:5000
```

## 默认账号

- **管理员用户名**: admin
- **管理员密码**: admin123

## 数据模型

```
Admin (管理员)
  - id, username, password_hash

Collector (收集者)
  - id, username, password_hash, created_at
  - 一对一关联 CollectionObject

CollectionObject (收集对象)
  - id, name, collector_id
  - 多对多关联 CollectionTheme (通过 ThemeObject)
  - 一对多关联 Attachment

CollectionTheme (收集主题)
  - id, title, description, announcement, deadline, is_active, collector_name
  - 多对多关联 CollectionObject (通过 ThemeObject)
  - 一对多关联 ThemeAttachment

ThemeObject (主题-对象关联)
  - id, theme_id, object_id, is_completed, completed_at

Attachment (附件)
  - id, filename, original_name, collection_object_id, uploaded_at

ThemeAttachment (主题附件)
  - id, filename, original_name, theme_id, uploaded_at

Announcement (公告)
  - id, title, content, created_at, updated_at
  - 一对多关联 AnnouncementAttachment

AnnouncementAttachment (公告附件)
  - id, filename, original_name, announcement_id, uploaded_at
```

## 目录结构

```
file-collection/
├── app.py                 # 应用入口
├── config.py              # 配置文件
├── models.py              # 数据模型
├── routes.py              # 路由和业务逻辑
├── utils.py               # 工具函数
├── requirements.txt       # Python 依赖
├── Dockerfile             # Docker 镜像构建
├── docker-compose.yml     # Docker Compose 配置
├── entrypoint.sh          # 容器启动脚本
├── DEPLOY.md              # 部署说明
├── app/
│   └── templates/         # HTML 模板
│       ├── collector_login.html        # 收集者登录页
│       ├── admin_objects.html          # 收集对象管理页
│       ├── admin_object_create.html    # 创建收集对象+账号
│       ├── admin_object_edit.html      # 编辑收集对象
│       └── admin_collector_reset_password.html  # 重置收集者密码
└── static/
    └── css/              # 样式文件
```

## 数据存储

- **上传文件**: `uploads/` 目录
- **数据库**: `instance/file_collection.db`

## API 端点

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 首页 |
| `/collector/login` | GET/POST | 收集者登录 |
| `/collector/logout` | GET | 收集者退出 |
| `/admin` | GET | 管理员后台 |
| `/admin/login` | POST | 管理员登录 |
| `/admin/objects` | GET | 收集对象管理 |
| `/admin/object/create` | GET/POST | 创建收集对象+账号 |
| `/admin/object/<id>/edit` | GET/POST | 编辑收集对象 |
| `/admin/object/<id>/reset-password` | GET/POST | 重置收集者密码 |
| `/theme/<id>` | GET | 主题详情 (需登录) |
| `/upload/<object_id>` | GET/POST | 文件上传 (需登录) |
| `/admin/theme/create` | POST | 创建主题 |
| `/admin/theme/<id>/export` | GET | 导出附件 |

## 使用流程

### 管理员操作
1. 登录管理员后台
2. 创建收集主题
3. 创建收集对象并关联登录账号（可同时关联多个主题）
4. 查看收集进度，管理收集对象

### 收集者操作
1. 使用管理员分配的账号登录
2. 查看分配给自己的收集主题
3. 上传附件
4. 完成上传后标记完成状态

## 许可证

MIT License
