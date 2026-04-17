from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
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
WORKFLOW_AUDIT_CONFIG_FILE = BASE_DIR / "workflow_audit_config.json"

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
        "id": "workflow-audit",
        "name": "Workflow Audit",
        "summary": "Scan the local backend project and verify workflow node/key mappings against real JSON files.",
        "status": "live",
        "path": "/workflow-audit",
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


def load_workflow_audit_config() -> Dict[str, Any]:
    return json.loads(WORKFLOW_AUDIT_CONFIG_FILE.read_text(encoding="utf-8"))


WORKFLOW_AUDIT_CONFIG = load_workflow_audit_config()


def get_backend_project_dir() -> Path:
    return Path(
        os.environ.get(
            "WORKFLOW_AUDIT_BACKEND_PATH",
            WORKFLOW_AUDIT_CONFIG["local_backend_path"],
        )
    )


def get_backend_router_files() -> Dict[str, Path]:
    backend_root = get_backend_project_dir()
    return {
        "root": backend_root,
        "routers_dir": backend_root / WORKFLOW_AUDIT_CONFIG["routers_relative_path"],
        "public": backend_root / WORKFLOW_AUDIT_CONFIG["public_router_file"],
        "workflow": backend_root / WORKFLOW_AUDIT_CONFIG["workflow_router_file"],
        "frw": backend_root / WORKFLOW_AUDIT_CONFIG["frw_router_file"],
    }


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


class WorkflowAuditRequest(BaseModel):
    scopes: Optional[List[str]] = None
    only_issues: bool = False
    branch: Optional[str] = None
    sync_first: bool = True


class WorkflowAuditSyncRequest(BaseModel):
    branch: Optional[str] = None


def _slice_to_text(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Name):
        return f"<dynamic:{node.id}>"
    try:
        return f"<expr:{ast.unparse(node)}>"
    except Exception:
        return "<dynamic>"


def _unwind_subscript_chain(node: ast.AST) -> Tuple[Optional[str], List[str]]:
    parts: List[str] = []
    current = node
    while isinstance(current, ast.Subscript):
        parts.append(_slice_to_text(current.slice))
        current = current.value
    if isinstance(current, ast.Name):
        return current.id, list(reversed(parts))
    return None, list(reversed(parts))


def _resolve_backend_workflow_path(raw_path: str) -> Path:
    cleaned = raw_path.strip()
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return get_backend_project_dir() / cleaned


def _load_json_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_workflow_target(
    workflow_json: Dict[str, Any], node_id: str, input_key: str
) -> Dict[str, Any]:
    node = workflow_json.get(str(node_id))
    if not isinstance(node, dict):
        return {
            "status": "error",
            "reason": "missing_node",
            "message": f"node {node_id} 不存在",
        }

    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        return {
            "status": "error",
            "reason": "missing_inputs",
            "message": f"node {node_id} 没有 inputs",
            "suggestion": None,
        }

    if input_key.startswith("<dynamic:") or "<dynamic:" in input_key or "<expr:" in input_key:
        return {
            "status": "warning",
            "reason": "dynamic_key",
            "message": f"node {node_id} 使用动态 key：{input_key}，需要人工确认",
            "suggestion": "这是动态 key 或表达式，建议打开对应 workflow JSON 手动确认 inputs 结构。",
        }

    first_key = input_key.split(".", 1)[0]
    if first_key not in inputs:
        available_keys = list(inputs.keys())
        suggestion: Optional[str] = None
        if first_key == "value":
            dimensional_keys = [key for key in available_keys if key in {"width", "height", "batch_size", "length", "frame_count"}]
            if dimensional_keys:
                suggestion = f"这个节点没有 value，但存在这些更像目标参数的 key：{', '.join(dimensional_keys)}"
        elif available_keys:
            suggestion = f"这个节点当前可用的 inputs key 有：{', '.join(available_keys[:8])}"
        return {
            "status": "error",
            "reason": "missing_key",
            "message": f"node {node_id} 缺少 key {first_key}",
            "suggestion": suggestion,
        }

    return {
        "status": "ok",
        "reason": "matched",
        "message": f"node {node_id} / key {input_key} 命中",
        "suggestion": None,
    }


def _summarize_item_status(checks: List[Dict[str, Any]], workflow_exists: bool) -> str:
    if not workflow_exists:
        return "error"
    if any(item["status"] == "error" for item in checks):
        return "error"
    if any(item["status"] == "warning" for item in checks):
        return "warning"
    return "ok"


def _extract_workflow_refs_from_function(node: ast.AST) -> List[Dict[str, str]]:
    refs: List[Dict[str, str]] = []
    for stmt in ast.walk(node):
        if not isinstance(stmt, ast.Assign):
            continue
        root, parts = _unwind_subscript_chain(stmt.value)
        if root in {
            "WorkPath",
            "WorkPath_Crypt",
            "AUDIT_WORKFLOW_PATH",
            "frw_workflow_integration_workflow_path",
        } and len(parts) == 1:
            refs.append({"map_name": root, "lookup_key": parts[0]})
        elif isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            if any(isinstance(t, ast.Name) and t.id == "workflow_path" for t in stmt.targets):
                refs.append({"map_name": "direct", "lookup_key": stmt.value.value})
    deduped: List[Dict[str, str]] = []
    seen = set()
    for ref in refs:
        key = (ref["map_name"], ref["lookup_key"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped


def _extract_workflow_mutations_from_function(node: ast.AST) -> List[Dict[str, str]]:
    mutations: List[Dict[str, str]] = []
    for stmt in ast.walk(node):
        targets: List[ast.AST] = []
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
        elif isinstance(stmt, ast.AugAssign):
            targets = [stmt.target]
        else:
            continue

        for target in targets:
            root, parts = _unwind_subscript_chain(target)
            if root not in {"workflow_data", "workflow"} or len(parts) < 3:
                continue
            node_id = parts[0]
            if len(parts) >= 3 and parts[1] == "inputs":
                input_key = ".".join(parts[2:])
                mutations.append(
                    {
                        "node": node_id,
                        "key": input_key,
                    }
                )
    deduped: List[Dict[str, str]] = []
    seen = set()
    for item in mutations:
        key = (item["node"], item["key"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _workflow_maps_for_audit() -> Dict[str, Dict[str, str]]:
    files = get_backend_router_files()
    return {
        "WorkPath": parse_named_dict(
            files["public"].read_text(encoding="utf-8"), "WorkPath"
        ),
        "WorkPath_Crypt": parse_named_dict(
            files["public"].read_text(encoding="utf-8"), "WorkPath_Crypt"
        ),
        "AUDIT_WORKFLOW_PATH": parse_named_dict(
            files["workflow"].read_text(encoding="utf-8"), "AUDIT_WORKFLOW_PATH"
        ),
        "frw_workflow_integration_workflow_path": parse_named_dict(
            files["frw"].read_text(encoding="utf-8"),
            "frw_workflow_integration_workflow_path",
        ),
    }


def _analyze_router_file(file_path: Path, workflow_maps: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    results: List[Dict[str, Any]] = []

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        refs = _extract_workflow_refs_from_function(node)
        mutations = _extract_workflow_mutations_from_function(node)
        if not refs or not mutations:
            continue

        for ref in refs:
            raw_path = ref["lookup_key"]
            if ref["map_name"] != "direct":
                raw_path = workflow_maps.get(ref["map_name"], {}).get(ref["lookup_key"], "")
            workflow_path = _resolve_backend_workflow_path(raw_path) if raw_path else None
            workflow_exists = bool(workflow_path and workflow_path.exists())
            workflow_json = _load_json_file(workflow_path) if workflow_exists else {}

            checks = []
            for mutation in mutations:
                outcome = _check_workflow_target(
                    workflow_json, mutation["node"], mutation["key"]
                ) if workflow_exists else {
                    "status": "error",
                    "reason": "missing_workflow",
                    "message": f"workflow 文件不存在：{raw_path}",
                }
                checks.append(
                    {
                        "node": mutation["node"],
                        "key": mutation["key"],
                        **outcome,
                    }
                )

            results.append(
                {
                    "kind": "router_function",
                    "source_file": str(file_path),
                    "source_name": node.name,
                    "map_name": ref["map_name"],
                    "lookup_key": ref["lookup_key"],
                    "workflow_path": raw_path,
                    "workflow_exists": workflow_exists,
                    "status": _summarize_item_status(checks, workflow_exists),
                    "checks": checks,
                }
            )
    return results


def _analyze_frw_patch_plan(workflow_maps: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
    files = get_backend_router_files()
    source = files["frw"].read_text(encoding="utf-8")
    patch_plan = parse_named_dict(source, "WORKFLOW_PATCH_PLAN")
    route_info = parse_route_task_types(source)
    task_type_to_route_meta: Dict[str, Dict[str, Any]] = {}
    for item in route_info:
        for task_type in item["task_types"]:
            task_type_to_route_meta[task_type] = item

    results: List[Dict[str, Any]] = []
    path_map = workflow_maps["frw_workflow_integration_workflow_path"]
    for task_type, plan in patch_plan.items():
        raw_path = path_map.get(task_type, "")
        workflow_path = _resolve_backend_workflow_path(raw_path) if raw_path else None
        workflow_exists = bool(workflow_path and workflow_path.exists())
        workflow_json = _load_json_file(workflow_path) if workflow_exists else {}
        mutations: List[Tuple[str, str]] = []

        for item in plan.get("urls", []):
            mutations.append((str(item.get("node", "")), str(item.get("key", ""))))
        for key in ("positive", "negative"):
            meta = plan.get(key)
            if isinstance(meta, dict):
                mutations.append((str(meta.get("node", "")), str(meta.get("key", ""))))
        for meta in (plan.get("params") or {}).values():
            if isinstance(meta, dict):
                mutations.append((str(meta.get("node", "")), str(meta.get("key", ""))))
        for key in ("lora", "lora2"):
            meta = plan.get(key)
            if isinstance(meta, dict):
                mutations.append((str(meta.get("node", "")), "<dynamic:lora_inputs>"))

        checks = []
        for node_id, input_key in mutations:
            outcome = _check_workflow_target(workflow_json, node_id, input_key) if workflow_exists else {
                "status": "error",
                "reason": "missing_workflow",
                "message": f"workflow 文件不存在：{raw_path}",
            }
            checks.append({"node": node_id, "key": input_key, **outcome})

        route_meta = task_type_to_route_meta.get(task_type, {})
        results.append(
            {
                "kind": "frw_task_type",
                "source_file": str(files["frw"]),
                "source_name": route_meta.get("function", task_type),
                "task_type": task_type,
                "routes": route_meta.get("routes", []),
                "workflow_path": raw_path,
                "workflow_exists": workflow_exists,
                "status": _summarize_item_status(checks, workflow_exists),
                "checks": checks,
            }
        )
    return results


def run_workflow_audit(scopes: Optional[List[str]] = None, only_issues: bool = False) -> Dict[str, Any]:
    requested = set(scopes or ["public", "workflow", "frw"])
    workflow_maps = _workflow_maps_for_audit()
    files = get_backend_router_files()
    items: List[Dict[str, Any]] = []

    if "public" in requested and files["public"].exists():
        items.extend(_analyze_router_file(files["public"], workflow_maps))
    if "workflow" in requested and files["workflow"].exists():
        items.extend(_analyze_router_file(files["workflow"], workflow_maps))
    if "frw" in requested and files["frw"].exists():
        items.extend(_analyze_frw_patch_plan(workflow_maps))

    if only_issues:
        items = [item for item in items if item["status"] != "ok"]

    grouped_issues: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        issue_checks = [check for check in item["checks"] if check["status"] != "ok"]
        if not issue_checks:
            continue
        for check in issue_checks:
            group_key = check["reason"]
            grouped_issues.setdefault(group_key, []).append(
                {
                    "source_name": item.get("task_type") or item["source_name"],
                    "source_file": item["source_file"],
                    "workflow_path": item["workflow_path"],
                    "node": check["node"],
                    "key": check["key"],
                    "status": check["status"],
                    "message": check["message"],
                }
            )

    summary = {
        "total_items": len(items),
        "ok": sum(1 for item in items if item["status"] == "ok"),
        "warning": sum(1 for item in items if item["status"] == "warning"),
        "error": sum(1 for item in items if item["status"] == "error"),
        "total_checks": sum(len(item["checks"]) for item in items),
    }
    return {
        "backend_root": str(files["root"]),
        "scopes": sorted(requested),
        "config": WORKFLOW_AUDIT_CONFIG,
        "git_steps": {
            "clone": f'git clone {WORKFLOW_AUDIT_CONFIG["repo_url"]} {files["root"]}',
            "checkout": f'cd {files["root"]} && git checkout <branch-name>',
            "pull": f'cd {files["root"]} && git pull',
        },
        "summary": summary,
        "grouped_issues": grouped_issues,
        "items": items,
    }


def sync_workflow_audit_repo(branch: Optional[str] = None) -> Dict[str, Any]:
    files = get_backend_router_files()
    backend_root = files["root"]
    target_branch = (branch or WORKFLOW_AUDIT_CONFIG.get("default_branch") or "main").strip()
    backend_root.parent.mkdir(parents=True, exist_ok=True)

    steps: List[Dict[str, Any]] = []

    def run_cmd(args: List[str], cwd: Optional[Path] = None) -> str:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            check=True,
            capture_output=True,
            text=True,
        )
        output = (completed.stdout or completed.stderr or "").strip()
        return output

    git_dir = backend_root / ".git"
    if not git_dir.exists():
        clone_output = run_cmd(
            ["git", "clone", WORKFLOW_AUDIT_CONFIG["repo_url"], str(backend_root)]
        )
        steps.append({"step": "clone", "status": "ok", "output": clone_output})
    else:
        steps.append({"step": "clone", "status": "skipped", "output": "Repository already exists"})

    fetch_output = run_cmd(["git", "fetch", "--all"], cwd=backend_root)
    steps.append({"step": "fetch", "status": "ok", "output": fetch_output})

    checkout_output = run_cmd(["git", "checkout", target_branch], cwd=backend_root)
    steps.append({"step": "checkout", "status": "ok", "output": checkout_output})

    pull_output = run_cmd(["git", "pull", "--ff-only", "origin", target_branch], cwd=backend_root)
    steps.append({"step": "pull", "status": "ok", "output": pull_output})

    current_branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=backend_root)
    current_commit = run_cmd(["git", "rev-parse", "HEAD"], cwd=backend_root)

    return {
        "backend_root": str(backend_root),
        "branch": current_branch,
        "commit": current_commit,
        "steps": steps,
    }


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


@app.get("/workflow-audit", response_class=HTMLResponse)
async def workflow_audit(request: Request) -> HTMLResponse:
    files = get_backend_router_files()
    return templates.TemplateResponse(
        "workflow_audit.html",
        {
            "request": request,
            "backend_root": str(files["root"]),
            "scopes": ["public", "workflow", "frw"],
            "audit_config": WORKFLOW_AUDIT_CONFIG,
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


@app.get("/api/workflow-audit/meta")
async def api_workflow_audit_meta() -> JSONResponse:
    files = get_backend_router_files()
    return JSONResponse(
        {
            "backend_root": str(files["root"]),
            "scopes": ["public", "workflow", "frw"],
            "config": WORKFLOW_AUDIT_CONFIG,
            "git_steps": {
                "clone": f'git clone {WORKFLOW_AUDIT_CONFIG["repo_url"]} {files["root"]}',
                "checkout": f'cd {files["root"]} && git checkout <branch-name>',
                "pull": f'cd {files["root"]} && git pull',
            },
            "files": {
                "public": str(files["public"]),
                "workflow": str(files["workflow"]),
                "frw": str(files["frw"]),
            },
        }
    )


@app.post("/api/workflow-audit/sync")
async def api_workflow_audit_sync(payload: WorkflowAuditSyncRequest) -> JSONResponse:
    try:
        return JSONResponse(sync_workflow_audit_repo(branch=payload.branch))
    except subprocess.CalledProcessError as exc:
        raise HTTPException(
            status_code=500,
            detail=(exc.stderr or exc.stdout or str(exc)).strip(),
        ) from exc


@app.post("/api/workflow-audit/run")
async def api_workflow_audit_run(payload: WorkflowAuditRequest) -> JSONResponse:
    sync_result = None
    if payload.sync_first:
        try:
            sync_result = sync_workflow_audit_repo(branch=payload.branch)
        except subprocess.CalledProcessError as exc:
            raise HTTPException(
                status_code=500,
                detail=(exc.stderr or exc.stdout or str(exc)).strip(),
            ) from exc

    result = run_workflow_audit(scopes=payload.scopes, only_issues=payload.only_issues)
    result["sync"] = sync_result
    return JSONResponse(result)


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
