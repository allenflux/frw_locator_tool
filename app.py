from __future__ import annotations

import ast
import json
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.requests import Request
import uvicorn

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FRW_FILE = DATA_DIR / "frw_workflow_integration.py"
CONFIG_FILE = DATA_DIR / "gatewayconfig1776334785642.json"

app = FastAPI(title="FRW Workflow Machine Locator", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

AVAILABLE_TOOLS: List[Dict[str, Any]] = [
    {
        "id": "locator",
        "name": "Workflow Locator",
        "summary": "Resolve task_type and queue mappings to machine names and ports.",
        "status": "live",
        "path": "/",
    },
    {
        "id": "workflow-builder",
        "name": "Workflow Builder",
        "summary": "Generate copy-ready snippets for new workflow endpoints without writing code by hand.",
        "status": "live",
        "path": "/workflow-builder",
    },
    {
        "id": "toolkit-slot",
        "name": "Toolkit Slot",
        "summary": "Reserved space for future internal utilities and diagnostics.",
        "status": "planned",
        "path": None,
    },
]


def _safe_literal_eval(node: ast.AST) -> Any:
    return ast.literal_eval(node)


def parse_named_dict(source: str, variable_name: str) -> Dict[str, Any]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == variable_name:
                    value = _safe_literal_eval(node.value)
                    if isinstance(value, dict):
                        return value
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == variable_name:
                value = _safe_literal_eval(node.value)
                if isinstance(value, dict):
                    return value
    raise ValueError(f"{variable_name} not found")


def parse_task_queue_map(source: str) -> Dict[str, str]:
    return parse_named_dict(source, "TASK_QUEUE_MAP")


def parse_route_task_types(source: str) -> List[Dict[str, Any]]:
    tree = ast.parse(source)
    results: List[Dict[str, Any]] = []

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        route_info: List[Dict[str, str]] = []
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            func = deco.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in {"post", "get", "put", "delete", "patch"}:
                continue
            if not deco.args:
                continue
            path = None
            if isinstance(deco.args[0], ast.Constant) and isinstance(deco.args[0].value, str):
                path = deco.args[0].value
            if path:
                route_info.append({"method": func.attr.upper(), "path": path})

        if not route_info:
            continue

        task_type_expr: Optional[ast.AST] = None
        task_type_value: Optional[str] = None
        model_param_name: Optional[str] = None
        enum_options: List[str] = []

        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == "task_type":
                        task_type_expr = stmt.value
                        try:
                            if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                                task_type_value = stmt.value.value
                            elif isinstance(stmt.value, ast.BinOp) and isinstance(stmt.value.op, ast.Add):
                                left = stmt.value.left
                                right = stmt.value.right
                                if isinstance(left, ast.Constant) and isinstance(left.value, str) and isinstance(right, ast.Name):
                                    task_type_value = f"{left.value}{{{right.id}}}"
                                    model_param_name = right.id
                        except Exception:
                            pass

        for arg in node.args.args:
            if arg.annotation and isinstance(arg.annotation, ast.Subscript):
                ann = arg.annotation
                if isinstance(ann.value, ast.Name) and ann.value.id == "Literal":
                    try:
                        slice_node = ann.slice
                        if isinstance(slice_node, ast.Tuple):
                            values = []
                            for elt in slice_node.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    values.append(elt.value)
                            if arg.arg == model_param_name:
                                enum_options = values
                    except Exception:
                        pass

        resolved_task_types: List[str] = []
        if task_type_value:
            if model_param_name and enum_options:
                for opt in enum_options:
                    resolved_task_types.append(task_type_value.format(**{model_param_name: opt}))
            else:
                resolved_task_types.append(task_type_value)

        results.append(
            {
                "function": node.name,
                "routes": route_info,
                "task_types": resolved_task_types,
                "model_param_name": model_param_name,
                "model_options": enum_options,
            }
        )
    return results


def load_configs() -> List[Dict[str, Any]]:
    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Config json must be a list")
    return data


def port_only(host: str) -> Optional[str]:
    parsed = urlparse(host)
    return str(parsed.port) if parsed.port else None


def build_index() -> Dict[str, Any]:
    source = FRW_FILE.read_text(encoding="utf-8")
    task_queue_map = parse_task_queue_map(source)
    route_task_types = parse_route_task_types(source)
    configs = load_configs()

    queue_to_machines: Dict[str, List[Dict[str, Any]]] = {}
    for item in configs:
        flows = item.get("flow") or []
        for flow in flows:
            queue_to_machines.setdefault(flow, []).append(
                {
                    "machine": item.get("name"),
                    "port": port_only(item.get("host", "")),
                    "connected": bool(item.get("isConneted")),
                    "play": bool(item.get("isPlay")),
                }
            )

    task_type_to_routes: Dict[str, List[Dict[str, str]]] = {}
    for route in route_task_types:
        for task_type in route["task_types"]:
            task_type_to_routes.setdefault(task_type, []).extend(route["routes"])

    return {
        "task_queue_map": task_queue_map,
        "queue_to_machines": queue_to_machines,
        "task_type_to_routes": task_type_to_routes,
        "route_task_types": route_task_types,
        "frw_source": source,
    }


INDEX = build_index()

WORKFLOW_FIELD_LIBRARY: Dict[str, Dict[str, Any]] = {
    "first_img_url": {
        "label": "首图 URL",
        "type_hint": "str",
        "form": 'Form(..., description="首图URL")',
        "category": "url",
        "default_enabled": True,
    },
    "last_img_url": {
        "label": "尾图 URL",
        "type_hint": "str",
        "form": 'Form(..., description="尾图URL")',
        "category": "url",
        "default_enabled": True,
    },
    "positive_prompt": {
        "label": "正向提示词",
        "type_hint": "str",
        "form": 'Form(..., description="正向提示词")',
        "category": "positive",
        "default_enabled": True,
    },
    "negative_prompt": {
        "label": "反向提示词",
        "type_hint": "str",
        "form": 'Form(default="", description="反向提示词")',
        "category": "negative",
        "default_enabled": True,
    },
    "width": {
        "label": "宽度",
        "type_hint": "int",
        "form": 'Form(default=480, description="视频宽度")',
        "category": "param",
        "default_enabled": True,
    },
    "height": {
        "label": "高度",
        "type_hint": "int",
        "form": 'Form(default=832, description="视频高度")',
        "category": "param",
        "default_enabled": True,
    },
    "frame_count": {
        "label": "帧数",
        "type_hint": "int",
        "form": 'Form(default=81, ge=80, description="总帧数")',
        "category": "param",
        "default_enabled": True,
    },
}

COMMON_FORM_FIELDS: List[str] = [
    'bid: Optional[str] = Form(None, description="业务编号")',
    'title: Optional[str] = Form(None, description="标题")',
    'notify_url: Optional[str] = Form(None, description="回调地址")',
    'hash_key: Optional[str] = Form(None, description="hash key")',
    'fee: int = Form(10, ge=0, description="费用")',
    'app_id: str = Form("", description="app_id")',
    'task_id: Optional[str] = Form(None, description="任务ID，不传自动生成")',
]

COMMON_DOCUMENT_FIELDS: List[str] = [
    "bid=bid if bid else task_id,",
    "notify_url=notify_url,",
    "fee=fee,",
    "app_id=app_id,",
    "title=title,",
    "hash_key=hash_key,",
]


class WorkflowBuilderRequest(BaseModel):
    task_type: str
    display_name: str
    workflow_file_name: str
    queue_name: str
    enabled_fields: List[str]
    mappings: Dict[str, Dict[str, str]]
    workflow_json: Optional[str] = None


def build_workflow_builder_meta() -> Dict[str, Any]:
    source = FRW_FILE.read_text(encoding="utf-8")
    task_queue_map = parse_named_dict(source, "TASK_QUEUE_MAP")
    workflow_path_map = parse_named_dict(
        source, "frw_workflow_integration_workflow_path"
    )
    patch_plan_map = parse_named_dict(source, "WORKFLOW_PATCH_PLAN")
    existing_task_types = sorted(
        set(task_queue_map.keys())
        | set(workflow_path_map.keys())
        | set(patch_plan_map.keys())
    )
    return {
        "existing_task_types": existing_task_types,
        "available_queues": sorted(set(task_queue_map.values())),
        "field_library": WORKFLOW_FIELD_LIBRARY,
        "workflow_directory": "./comfyui_workflow/FRW_Workflow_Integration/",
    }


WORKFLOW_BUILDER_META = build_workflow_builder_meta()


def normalize_task_type(task_type: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", task_type.strip().lower()).strip("_")
    if not normalized:
        raise HTTPException(status_code=400, detail="task_type 不能为空")
    return normalized


def make_function_name(task_type: str) -> str:
    function_name = normalize_task_type(task_type)
    if function_name[0].isdigit():
        function_name = f"workflow_{function_name}"
    return function_name


def make_workflow_path(file_name: str) -> str:
    cleaned = file_name.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="工作流文件名不能为空")
    if cleaned.startswith("./comfyui_workflow/FRW_Workflow_Integration/"):
        return cleaned
    if "/" in cleaned:
        return cleaned
    return f'./comfyui_workflow/FRW_Workflow_Integration/{cleaned}'


def _validate_mapping_against_workflow_json(
    workflow_json: Optional[str], field: str, node_id: str, key: str
) -> Optional[str]:
    if not workflow_json:
        return None
    try:
        parsed = json.loads(workflow_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"workflow JSON 不是合法 JSON: {exc}")

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="workflow JSON 顶层必须是对象")

    node = parsed.get(str(node_id))
    if not isinstance(node, dict):
        raise HTTPException(
            status_code=400,
            detail=f"字段 {field} 指向的节点 {node_id} 在 workflow JSON 中不存在",
        )

    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise HTTPException(
            status_code=400,
            detail=f"字段 {field} 的节点 {node_id} 没有 inputs 结构",
        )

    if key not in inputs:
        raise HTTPException(
            status_code=400,
            detail=f"字段 {field} 的节点 {node_id} 不包含输入键 {key}",
        )
    return node.get("class_type")


def _build_patch_plan_entry(
    task_type: str,
    enabled_fields: List[str],
    mappings: Dict[str, Dict[str, str]],
    workflow_json: Optional[str],
) -> str:
    url_items: List[str] = []
    positive_line: Optional[str] = None
    negative_line: Optional[str] = None
    param_items: List[str] = []

    for field in enabled_fields:
        mapping = mappings.get(field) or {}
        node_id = str(mapping.get("node", "")).strip()
        key = str(mapping.get("key", "")).strip()
        if not node_id or not key:
            raise HTTPException(
                status_code=400,
                detail=f"字段 {field} 缺少 node 或 key 映射",
            )

        class_type = _validate_mapping_against_workflow_json(
            workflow_json, field, node_id, key
        )
        category = WORKFLOW_FIELD_LIBRARY[field]["category"]

        if category == "url":
            url_items.append(
                f'            {{"field": "{field}", "node": "{node_id}", "key": "{key}"}},'
            )
        elif category == "positive":
            positive_line = (
                f'        "positive": {{"node": "{node_id}", "key": "{key}"'
                + (f', "class_type": "{class_type}"' if class_type else "")
                + "},"
            )
        elif category == "negative":
            negative_line = (
                f'        "negative": {{"node": "{node_id}", "key": "{key}"'
                + (f', "class_type": "{class_type}"' if class_type else "")
                + "},"
            )
        else:
            param_items.append(
                f'            "{field}": {{"node": "{node_id}", "key": "{key}"}},'
            )

    lines = [f'    "{task_type}": {{']
    if url_items:
        lines.append('        "urls": [')
        lines.extend(url_items)
        lines.append("        ],")
    if positive_line:
        lines.append(positive_line)
    else:
        lines.append('        "positive": None,')
    if negative_line:
        lines.append(negative_line)
    else:
        lines.append('        "negative": None,')
    if param_items:
        lines.append('        "params": {')
        lines.extend(param_items)
        lines.append("        },")
    else:
        lines.append('        "params": {},')
    lines.append("    },")
    return "\n".join(lines)


def _build_endpoint_code(
    task_type: str,
    display_name: str,
    enabled_fields: List[str],
) -> str:
    function_name = make_function_name(task_type)
    route_path = f"/api/public/{task_type}"

    form_lines = [
        f'    {field}: {WORKFLOW_FIELD_LIBRARY[field]["type_hint"]} = {WORKFLOW_FIELD_LIBRARY[field]["form"]},'
        for field in enabled_fields
    ]
    form_lines.extend(f"    {field}," for field in COMMON_FORM_FIELDS)

    document_lines = [f"        {field}={field}," for field in enabled_fields]
    document_lines.extend(f"        {field}" for field in COMMON_DOCUMENT_FIELDS)

    patch_lines = [f"        {field}={field}," for field in enabled_fields]

    form_block = textwrap.indent("\n".join(form_lines), " " * 4)
    document_block = textwrap.indent("\n".join(document_lines), " " * 4)
    patch_block = textwrap.indent("\n".join(patch_lines), " " * 4)

    endpoint_code = f"""
    @router.post(
        "{route_path}",
        tags=["frwi"],
        name="{display_name}",
        include_in_schema=True,
    )
    async def {function_name}(
        request: Request,
{form_block}
    ):
        if not task_id:
            task_id = str(uuid4())

        task_type = "{task_type}"

        document = Document(
            uuid=task_id,
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
{document_block}
        )

        workflow = load_workflow(task_type)
        patch_workflow(
            workflow,
            task_type,
{patch_block}
        )

        queue_name = get_queue_by_task_type(task_type)

        logger.info(
            f"Publishing: task_type={{task_type}}, task_id={{task_id}}, queue={{queue_name}}"
        )

        await rabbitmq.publish(
            queue_name=queue_name,
            message=json.dumps(workflow, ensure_ascii=False),
            correlation_id=task_id,
        )

        await storage.save("mqtask", document.to_dict())
        await mongodb2.save("mqtask", document.to_dict())

        return JSONResponse(content=document.to_dict())
    """
    return textwrap.dedent(endpoint_code).strip()


def resolve_by_task_type(task_type: str) -> Dict[str, Any]:
    queue_name = INDEX["task_queue_map"].get(task_type)
    if not queue_name:
        raise HTTPException(status_code=404, detail=f"task_type not found: {task_type}")

    machines = INDEX["queue_to_machines"].get(queue_name, [])
    routes = INDEX["task_type_to_routes"].get(task_type, [])
    return {
        "task_type": task_type,
        "queue_name": queue_name,
        "routes": routes,
        "machines": machines,
        "machine_names": [m["machine"] for m in machines],
        "ports": [m["port"] for m in machines if m.get("port")],
        "recommended_machine": machines[0]["machine"] if machines else None,
        "recommended_port": machines[0]["port"] if machines else None,
    }


def resolve_by_queue(queue_name: str) -> Dict[str, Any]:
    task_types = sorted([k for k, v in INDEX["task_queue_map"].items() if v == queue_name])
    machines = INDEX["queue_to_machines"].get(queue_name, [])
    if not task_types and not machines:
        raise HTTPException(status_code=404, detail=f"queue_name not found: {queue_name}")
    return {
        "queue_name": queue_name,
        "task_types": task_types,
        "machines": machines,
        "machine_names": [m["machine"] for m in machines],
        "ports": [m["port"] for m in machines if m.get("port")],
    }


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    example = resolve_by_task_type("manju_tushengtu_1_qwen")
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "task_type_count": len(INDEX["task_queue_map"]),
            "queue_count": len(INDEX["queue_to_machines"]),
            "example": example,
            "tools": AVAILABLE_TOOLS,
        },
    )


@app.get("/workflow-builder", response_class=HTMLResponse)
async def workflow_builder(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "workflow_builder.html",
        {
            "request": request,
            "tool_count": len(WORKFLOW_BUILDER_META["existing_task_types"]),
            "queue_count": len(WORKFLOW_BUILDER_META["available_queues"]),
            "available_queues": WORKFLOW_BUILDER_META["available_queues"],
            "field_library": WORKFLOW_FIELD_LIBRARY,
            "workflow_directory": WORKFLOW_BUILDER_META["workflow_directory"],
        },
    )


@app.get("/api/resolve")
async def api_resolve(
    task_type: Optional[str] = Query(default=None),
    queue_name: Optional[str] = Query(default=None),
) -> JSONResponse:
    if task_type:
        return JSONResponse(resolve_by_task_type(task_type))
    if queue_name:
        return JSONResponse(resolve_by_queue(queue_name))
    raise HTTPException(status_code=400, detail="task_type or queue_name is required")


@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1)) -> JSONResponse:
    ql = q.strip().lower()
    matches: List[Dict[str, Any]] = []

    for task_type, queue_name in INDEX["task_queue_map"].items():
        if ql in task_type.lower() or ql in queue_name.lower():
            data = resolve_by_task_type(task_type)
            matches.append(data)

    seen = set()
    deduped = []
    for item in matches:
        key = item["task_type"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return JSONResponse({"query": q, "count": len(deduped), "items": deduped[:100]})


@app.get("/api/routes")
async def api_routes() -> JSONResponse:
    return JSONResponse(INDEX["route_task_types"])


@app.get("/api/tools")
async def api_tools() -> JSONResponse:
    return JSONResponse({"items": AVAILABLE_TOOLS})


@app.get("/api/workflow-builder/meta")
async def api_workflow_builder_meta() -> JSONResponse:
    return JSONResponse(WORKFLOW_BUILDER_META)


@app.post("/api/workflow-builder/generate")
async def api_workflow_builder_generate(payload: WorkflowBuilderRequest) -> JSONResponse:
    task_type = normalize_task_type(payload.task_type)
    if task_type in WORKFLOW_BUILDER_META["existing_task_types"]:
        raise HTTPException(
            status_code=400,
            detail=f"task_type 已存在：{task_type}，请换一个唯一名称",
        )

    if payload.queue_name not in WORKFLOW_BUILDER_META["available_queues"]:
        raise HTTPException(status_code=400, detail="请选择已有的 MQ queue")

    enabled_fields = [field for field in payload.enabled_fields if field in WORKFLOW_FIELD_LIBRARY]
    if not enabled_fields:
        raise HTTPException(status_code=400, detail="请至少选择一个参数")

    workflow_path = make_workflow_path(payload.workflow_file_name)
    display_name = payload.display_name.strip() or task_type
    function_name = make_function_name(task_type)
    route_path = f"/api/public/{task_type}"

    patch_plan_entry = _build_patch_plan_entry(
        task_type=task_type,
        enabled_fields=enabled_fields,
        mappings=payload.mappings,
        workflow_json=payload.workflow_json,
    )
    endpoint_code = _build_endpoint_code(
        task_type=task_type,
        display_name=display_name,
        enabled_fields=enabled_fields,
    )

    selected_fields = [
        {
            "field": field,
            "label": WORKFLOW_FIELD_LIBRARY[field]["label"],
            "node": payload.mappings.get(field, {}).get("node", ""),
            "key": payload.mappings.get(field, {}).get("key", ""),
        }
        for field in enabled_fields
    ]

    combined = "\n\n".join(
        [
            "# 1. TASK_QUEUE_MAP 新增项",
            f'    "{task_type}": "{payload.queue_name}",',
            "# 2. frw_workflow_integration_workflow_path 新增项",
            f'    "{task_type}": "{workflow_path}",',
            "# 3. WORKFLOW_PATCH_PLAN 新增项",
            patch_plan_entry,
            "# 4. Endpoints 区域新增接口",
            endpoint_code,
        ]
    )

    return JSONResponse(
        {
            "task_type": task_type,
            "function_name": function_name,
            "route_path": route_path,
            "workflow_path": workflow_path,
            "queue_name": payload.queue_name,
            "selected_fields": selected_fields,
            "copy_instruction": {
                "directory": WORKFLOW_BUILDER_META["workflow_directory"],
                "file_name": Path(workflow_path).name,
                "summary": f"先把工作流文件复制到 {WORKFLOW_BUILDER_META['workflow_directory']} 目录下，再把下面 4 段代码粘贴进 frw_workflow_integration.py。",
            },
            "snippets": {
                "task_queue_map": f'    "{task_type}": "{payload.queue_name}",',
                "workflow_path_map": f'    "{task_type}": "{workflow_path}",',
                "workflow_patch_plan": patch_plan_entry,
                "endpoint": endpoint_code,
                "combined": combined,
            },
        }
    )


@app.get("/source/frw_workflow_integration.py", response_class=PlainTextResponse)
async def source_file() -> PlainTextResponse:
    return PlainTextResponse(INDEX["frw_source"], media_type="text/x-python")


@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    uvicorn.run("app:app", host="0.0.0.0", port=8099, reload=False)


if __name__ == "__main__":
    main()
