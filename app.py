from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
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
        "id": "toolkit-slot",
        "name": "Toolkit Slot",
        "summary": "Reserved space for future internal utilities and diagnostics.",
        "status": "planned",
        "path": None,
    },
]


def _safe_literal_eval(node: ast.AST) -> Any:
    return ast.literal_eval(node)


def parse_task_queue_map(source: str) -> Dict[str, str]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TASK_QUEUE_MAP":
                    return _safe_literal_eval(node.value)
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "TASK_QUEUE_MAP":
                return _safe_literal_eval(node.value)
    raise ValueError("TASK_QUEUE_MAP not found")


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
