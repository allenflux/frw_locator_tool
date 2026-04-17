# FRW Workflow Locator

一个用于查询 `task_type`、`mq queue` 与目标机器映射关系的 FastAPI 小工具。

## 这次整理后的内容

- 前端支持中英双语切换，页面结构更适合跨团队共享
- 查询结果拆成更清晰的卡片视图，同时保留原始 JSON
- 首页已经预留 future toolkit 区域，方便后续继续挂内部小工具
- 新增 Workflow Builder，可为新工作流自动生成可复制代码
- 新增 Workflow Audit，可扫描本机 backend 项目并检查 API 与 workflow JSON 的 node/key 配对
- Workflow Audit 的仓库地址、本地目录、目标文件路径已独立到 `workflow_audit_config.json`
- 提供 `/api/tools` 元数据接口，便于后续做导航或聚合页
- 已补齐 Dockerfile、`.dockerignore` 和 `docker-compose.yml`

## 本地启动

```bash
cd frw_locator_tool
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8099
```

打开 [http://127.0.0.1:8099](http://127.0.0.1:8099)

工作流新增助手入口：

- [http://127.0.0.1:8099/workflow-builder](http://127.0.0.1:8099/workflow-builder)
- [http://127.0.0.1:8099/workflow-audit](http://127.0.0.1:8099/workflow-audit)

Workflow Audit 流程：

1. 先按 `workflow_audit_config.json` 里的仓库地址执行 `git clone`
2. 进入本地 backend 目录后切到目标分支
3. 执行 `git pull`
4. 回到工具页面运行检查

## Docker 启动

### 方式 1：直接 build/run

```bash
docker build -t frw-locator .
docker run --rm -p 8099:8099 frw-locator
```

### 方式 2：docker compose

```bash
docker compose up --build
```

## API

### 1. 按 task_type 查

```bash
curl 'http://127.0.0.1:8099/api/resolve?task_type=ai_chuangzuo_tushengshipin'
```

### 2. 按 queue 查

```bash
curl 'http://127.0.0.1:8099/api/resolve?queue_name=wan22_i2vhigh_frw_video_h'
```

### 3. 模糊搜索

```bash
curl 'http://127.0.0.1:8099/api/search?q=qwen_qwen19_frw_img_h'
```

### 4. 工具位元数据

```bash
curl 'http://127.0.0.1:8099/api/tools'
```

### 5. 工作流代码生成

```bash
curl 'http://127.0.0.1:8099/api/workflow-builder/meta'
```

## 后续扩展建议

- 新的小工具可以继续挂在 `AVAILABLE_TOOLS` 里，首页会自动显示卡片
- 如果后面想拆成多页，可以继续把每个工具做成独立路由，例如 `/tools/batch-resolver`
- 如果要接更完整的国际化，可以把当前页面内的 `i18n` 文案再独立成静态 JSON 文件

## 已内置的数据文件

- `data/frw_workflow_integration.py`
- `data/gatewayconfig1776334785642.json`
