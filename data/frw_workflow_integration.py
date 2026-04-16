# -*- coding: utf-8 -*-
"""
Generated on 2026-01-30T14:41:22
FRW public API (hardcoded workflow patching based on workflow json node ids)
"""

import copy
import json
import validators
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Literal
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Form, HTTPException, Request
from starlette.responses import JSONResponse
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend

from src.document import Document
from src.models.enum import TaskStatus
from src.mq.rabbitmq import RabbitMQ, get_rabbitmq_instance
from src.storage.storage import Storage, get_storage_instance
from src.storage.mongo2 import MongoDB2
from src.logger import getLogger

logger = getLogger(__name__)

rabbitmq: RabbitMQ = get_rabbitmq_instance()
storage: Storage = get_storage_instance()
mongodb2 = MongoDB2()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await rabbitmq.connect()
    redis = storage.redis.client
    FastAPICache.init(RedisBackend(redis), prefix="fr-cache")
    yield


router = APIRouter(lifespan=lifespan)

# ---------------- MQ Queue Routing ----------------

TASK_QUEUE_MAP: Dict[str, str] = {
    # ============================================
    # WAN 2.2  VIDEO  (H200 - 极重)
    # ============================================
    "manju_shouwei_zhen": "wan22_i2vhigh_frw_video_h",
    "manju_tushengshipin": "wan22_i2vhigh_frw_video_h",
    "ai_chuangzuo_wenshengshipin": "wan21_t2v14b_frw_video_h",
    "ai_chuangzuo_tushengshipin": "wan22_i2vhigh_frw_video_h",
    # ============================================
    # WAN 2.1  SWAP (更容易OOM，独立)
    # ============================================
    "shipin_huanyi": "wan22_i2vhigh_frw_video_h",
    "huanlian": "wan22_i2vhigh_frw_swap_h",
    # ============================================
    # SeedVR Upscale (H200 - 高显存)
    # ============================================
    "ai_chuangzao_chaoqing_fangda": "seedvr2_3b_frw_upscale_h",
    "ai_chuangzao_chaoqing_fangda_2": "seedvr2_7b_frw_upscale_h",
    # ============================================
    # Flux Heavy Image (H200)
    # ============================================
    "manju_tushengtu_1_qwen": "qwen_qwen19_frw_img_h",
    "manju_tushengtu_1_flux": "flux_iniverseMix_frw_img_h",
    "manju_tushengtu_2_qwen": "qwen_qwen19_frw_img_h",
    "manju_tushengtu_2_flux": "flux_fluxQ4_frw_img_h",
    "manju_tushengtu_3_qwen": "qwen_qwen19_frw_img_h",
    "manju_tushengtu_3_flux": "flux_iniverseMix_frw_img_h",
    "manju_tushengtu_4_qwen": "qwen_qwen19_frw_img_h",
    "manju_tushengtu_4_flux": "flux_iniverseMix_frw_img_h",
    "tushengtu": "ponyxl_ponycosplay_frw_img_m",
    "tushengtu_fengge_zhuanhuan": "qwen_qwen19_frw_img_h",
    "huanlian_2": "qwen_qwen19_frw_img_h",
    # ============================================
    # PonyXL img2img (5090)
    # ============================================
    "manju_tushengtu_dongman_fengge": "ponyxl_ponycosplay_frw_img_m",
    "huanzhuang": "flux_fluxfilldev_frw_t2i_m",
    # ============================================
    # PonyXL text2img (5090 主力)
    # ============================================
    "manju_wenshengtu_juese_shengcheng": "ponyxl_ponycosplay_frw_img_m",
    "ai_chuangzuo_wenshengtu_dongman_fengge_ponyxl": "ponyxl_visionary_frw_t2i_m",
    "ai_chuangzuo_wenshengtu_dongman_fengge_ponyxl2d": "ponyxl_hassaku_frw_t2i_m",
    "ai_chuangzuo_wenshengtu_dongman_fengge_ponyxl3d": "ponyxl_meichidark_frw_t2i_m",
    "ai_chuangzuo_wenshengtu_xieshi_fengge": "flux_fluxdev_frw_t2i_m",
    # ============================================
    # ControlNet / Edit (5090)
    # ============================================
    "tushengtu_dongzuo_bianji": "ponyxl_ponycosplay_frw_img_m",
    "heibai_zhaoxiufu": "flux_fluxkontext_frw_edit_m",
    "tushengtu_jubu_tuya": "qwen_qwen19_frw_edit_m",
    "tushengtu_tuya_chonghui": "qwen_qwen19_frw_edit_m",
    "tushengtu_tuya_chonghui_2": "flux_fluxfill_frw_edit_m",
    "tushengtu_beiying_zhuanhuan": "ponyx_pornmaster_frw_edit_m",
    "dongzuo_kelong_shengtu": "qwen_qwen19_frw_img_h",
    "dongzuo_kelong_shengshipin": "pose_transfer_video",
}


def get_queue_by_task_type(task_type: str) -> str:
    return TASK_QUEUE_MAP.get(task_type)


# task_type -> workflow json file path
frw_workflow_integration_workflow_path: Dict[str, str] = {
    # 'manju_shouwei_zhen': './comfyui_workflow/FRW_Workflow_Integration/wan2.2_swz_url.json',
    "manju_shouwei_zhen": "./comfyui_workflow/FRW_Workflow_Integration/WAN-SE-ClothesSwap-H264-url_API-ZOE.json",
    # 'manju_tushengshipin': './comfyui_workflow/FRW_Workflow_Integration/wan2.2-lightx2v-sageattn-seedvr2-1080p.json',
    "manju_tushengshipin": "./comfyui_workflow/FRW_Workflow_Integration/wan2.2-lightx2v-sageattn-seedvr2-1080p_API-ZOE_1.json",
    "manju_tushengtu_1_qwen": "./comfyui_workflow/FRW_Workflow_Integration/qwen-rapid-aio-img2img-1charater-swapface.json",
    "manju_tushengtu_1_flux": "./comfyui_workflow/FRW_Workflow_Integration/flux_pulid-img2img-teacache-4steps-gguf-url.json",
    "manju_tushengtu_2_qwen": "./comfyui_workflow/FRW_Workflow_Integration/qwen-rapid-aio-img2img-2charater-scence.json",
    "manju_tushengtu_2_flux": "./comfyui_workflow/FRW_Workflow_Integration/flux-pulid-two-charactor-teacace-url.json",
    "manju_tushengtu_3_qwen": "./comfyui_workflow/FRW_Workflow_Integration/qwen-rapid-aio-img2img-1charater-faceswap-style-transfer.json",
    "manju_tushengtu_3_flux": "./comfyui_workflow/FRW_Workflow_Integration/flux-ipadptor-pulid-mix-1charactor-4steps-gguf.json",
    "manju_tushengtu_4_qwen": "./comfyui_workflow/FRW_Workflow_Integration/qwen-rapid-aio-img2img-genneral.json",
    "manju_tushengtu_4_flux": "./comfyui_workflow/FRW_Workflow_Integration/flux-ipadptor-4steps-gguf-url.json",
    "manju_tushengtu_dongman_fengge": "./comfyui_workflow/FRW_Workflow_Integration/ponyxl_image2image-ipadaptor_lorastack_facerepiar_upscale_resize-vae-url.json",
    "manju_wenshengtu_juese_shengcheng": "./comfyui_workflow/FRW_Workflow_Integration/ponyxlv2_txt2img-clip-fiction.json",
    "ai_chuangzuo_wenshengtu_dongman_fengge_ponyxl": "./comfyui_workflow/FRW_Workflow_Integration/ponyxlv2_txt2img-ANIME-clip.json",
    "ai_chuangzuo_wenshengtu_dongman_fengge_ponyxl2d": "./comfyui_workflow/FRW_Workflow_Integration/ponyxlv2_NEW-2D.json",
    "ai_chuangzuo_wenshengtu_dongman_fengge_ponyxl3d": "./comfyui_workflow/FRW_Workflow_Integration/ponyxlv2_NEW-3D.json",
    "ai_chuangzuo_wenshengtu_xieshi_fengge": "./comfyui_workflow/FRW_Workflow_Integration/flux_text2img-teacache-url_API-ZOE.json",
    "tushengtu_fengge_zhuanhuan": "./comfyui_workflow/FRW_Workflow_Integration/image2image_flux_style_transfer_v2_API-ZOE_.json",
    "ai_chuangzuo_wenshengshipin": "./comfyui_workflow/FRW_Workflow_Integration/text_to_video_wan_API-ZOE_.json",
    "ai_chuangzuo_tushengshipin": "./comfyui_workflow/FRW_Workflow_Integration/wan2.2-lightx2v-sageattn-seedvr2-1080p_API-ZOE_1.json",
    "ai_chuangzao_chaoqing_fangda": "./comfyui_workflow/FRW_Workflow_Integration/seedvr2-v2.5.10-1080-gguf.json",
    # 'tushengtu_dongzuo_bianji': './comfyui_workflow/FRW_Workflow_Integration/image_qwen_image_edit_2509_gguf.json',
    "tushengtu_dongzuo_bianji": "./comfyui_workflow/FRW_Workflow_Integration/image_qwen_image_4steps_gguf-_EZIO.json",
    "heibai_zhaoxiufu": "./comfyui_workflow/FRW_Workflow_Integration/image_scale_fix_url.json",
    "ai_chuangzao_chaoqing_fangda_2": "./comfyui_workflow/FRW_Workflow_Integration/seedvr2-v2.5.10-2160.json",
    "tushengtu": "./comfyui_workflow/FRW_Workflow_Integration/ponyxl_image2image-ipadaptor_lorastack_facerepiar_upscale_resize-vae-url.json",
    "shipin_huanyi": "./comfyui_workflow/FRW_Workflow_Integration/WAN-SE-ClothesSwap-H264-url_API-ZOE.json",
    "huanlian": "./comfyui_workflow/FRW_Workflow_Integration/video-swapface-reactor-real-url.json",
    "huanlian_2": "./comfyui_workflow/FRW_Workflow_Integration/flux-pulid-two-charactor-teacace-url_API-ZOE.json",
    "huanzhuang": "./comfyui_workflow/FRW_Workflow_Integration/tryon-automask-teacache-url-gguf.json",
    "tushengtu_jubu_tuya": "./comfyui_workflow/FRW_Workflow_Integration/common_image2image_ipadaptor_inpaint_API-ZOE.json",
    "tushengtu_tuya_chonghui": "./comfyui_workflow/FRW_Workflow_Integration/controlnet_url_API-ZOE.json",
    "tushengtu_tuya_chonghui_2": "./comfyui_workflow/FRW_Workflow_Integration/alimama_flux_controlnet_inpaint_url_text_API-ZOE.json",
    "tushengtu_beiying_zhuanhuan": "./comfyui_workflow/FRW_Workflow_Integration/image2image_ipadapter_controlnet_transfer_API-ZOE.json",
    "dongzuo_kelong_shengtu": "./comfyui_workflow/FRW_Workflow_Integration/qwen-edit-dzkl-img.json",
    "dongzuo_kelong_shengshipin": "./comfyui_workflow/FRW_Workflow_Integration/wan2.2_fun_pose_transfer-reactor-gguf-url-tbacc.json",
}

# task_type -> patch plan (ALL hardcoded based on json node ids; NO runtime auto-adaptation)
WORKFLOW_PATCH_PLAN: Dict[str, Dict[str, Any]] = {
    "manju_shouwei_zhen": {
        "urls": [
            {"field": "first_img_url", "node": "38", "key": "url"},
            {"field": "last_img_url", "node": "39", "key": "url"},
        ],
        "positive": {"node": "7", "key": "text"},
        "negative": {"node": "8", "key": "text"},
        "params": {
            "width": {"node": "44", "key": "value"},
            "height": {"node": "46", "key": "value"},
            "frame_count": {"node": "48", "key": "value"},
        },
    },
    "manju_tushengshipin": {
        "urls": [
            {"field": "img_url", "node": "123", "key": "url"},
        ],
        "positive": {
            "node": "6",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "7",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "params": {
            "width": {"node": "143", "key": "width"},
            "height": {"node": "143", "key": "height"},
            "frame_count": {"node": "144", "key": "value"},
        },
    },
    "manju_tushengtu_1_qwen": {
        "urls": [
            {"field": "img_url", "node": "29", "key": "url"},
        ],
        "positive": {
            "node": "20",
            "key": "prompt",
            "class_type": "CLIPTextEncode",
        },
        "negative": None,
        "params": {
            "width": {"node": "28", "key": "width"},
            "height": {"node": "28", "key": "height"},
            "batch_size": {"node": "28", "key": "batch_size"},
        },
    },
    "manju_tushengtu_1_flux": {
        "urls": [
            {"field": "img_url", "node": "39", "key": "url"},
        ],
        "positive": {
            "node": "6",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": None,
        "params": {
            "width": {"node": "27", "key": "width"},
            "height": {"node": "27", "key": "height"},
            "batch_size": {"node": "27", "key": "batch_size"},
        },
    },
    "manju_tushengtu_2_qwen": {
        "urls": [
            {"field": "female_img_url", "node": "29", "key": "url"},
            {"field": "male_img_url", "node": "30", "key": "url"},
        ],
        "positive": {
            "node": "20",
            "key": "prompt",
            "class_type": "CLIPTextEncode",
        },
        "negative": None,
        "params": {
            "width": {"node": "28", "key": "width"},
            "height": {"node": "28", "key": "height"},
            "batch_size": {"node": "28", "key": "batch_size"},
        },
    },
    "manju_tushengtu_2_flux": {
        "urls": [
            {"field": "female_img_url", "node": "200", "key": "url"},
            {"field": "male_img_url", "node": "199", "key": "url"},
        ],
        "positive": {
            "node": "191",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": None,
        "params": {
            "width": {"node": "113", "key": "width"},
            "height": {"node": "113", "key": "height"},
            "batch_size": {"node": "113", "key": "batch_size"},
        },
    },
    "manju_tushengtu_3_qwen": {
        "urls": [
            {"field": "img_url", "node": "29", "key": "url"},
        ],
        "positive": {
            "node": "20",
            "key": "prompt",
            "class_type": "CLIPTextEncode",
        },
        "negative": None,
        "params": {
            "width": {"node": "28", "key": "width"},
            "height": {"node": "28", "key": "height"},
            "batch_size": {"node": "28", "key": "batch_size"},
        },
    },
    "manju_tushengtu_3_flux": {
        "urls": [
            {"field": "img_url", "node": "89", "key": "url"},
        ],
        "positive": {
            "node": "87",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": None,
        "params": {
            "width": {"node": "77", "key": "width"},
            "height": {"node": "77", "key": "height"},
            "batch_size": {"node": "77", "key": "batch_size"},
        },
    },
    "manju_tushengtu_4_qwen": {
        "urls": [
            {"field": "img_url", "node": "29", "key": "url"},
        ],
        "positive": {
            "node": "20",
            "key": "prompt",
            "class_type": "CLIPTextEncode",
        },
        "negative": None,
        "params": {
            "width": {"node": "28", "key": "width"},
            "height": {"node": "28", "key": "height"},
            "batch_size": {"node": "28", "key": "batch_size"},
        },
    },
    "manju_tushengtu_4_flux": {
        "urls": [
            {"field": "img_url", "node": "89", "key": "url"},
        ],
        "positive": {
            "node": "87",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": None,
        "params": {
            "width": {"node": "77", "key": "width"},
            "height": {"node": "77", "key": "height"},
            "batch_size": {"node": "77", "key": "batch_size"},
        },
    },
    "manju_tushengtu_dongman_fengge": {
        "urls": [
            {"field": "img_url", "node": "88", "key": "url"},
        ],
        "positive": {
            "node": "22",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "23",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "params": {
            "width": {"node": "89", "key": "value"},
            "height": {"node": "90", "key": "value"},
            "batch_size": {"node": "5", "key": "batch_size"},
        },
    },
    "manju_wenshengtu_juese_shengcheng": {
        "urls": [],
        "positive": {
            "node": "6",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "7",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "params": {
            "width": {"node": "5", "key": "width"},
            "height": {"node": "5", "key": "height"},
            "batch_size": {"node": "5", "key": "batch_size"},
        },
    },
    "ai_chuangzuo_wenshengtu_dongman_fengge_ponyxl": {
        "urls": [],
        "positive": {
            "node": "6",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "7",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "lora": {"node": "75"},
        "params": {
            "width": {"node": "5", "key": "width"},
            "height": {"node": "5", "key": "height"},
            "batch_size": {"node": "5", "key": "batch_size"},
            "cfg_scale": {"node": "61", "key": "cfg"},
            "sampler": {"node": "61", "key": "sampler_name"},
            "steps": {"node": "61", "key": "steps"},
            "seed": {"node": "61", "key": "seed"},
        },
    },
    "ai_chuangzuo_wenshengtu_dongman_fengge_ponyxl2d": {
        "urls": [],
        "positive": {
            "node": "6",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "7",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "lora": {"node": "101"},
        "params": {
            "width": {"node": "5", "key": "width"},
            "height": {"node": "5", "key": "height"},
            "batch_size": {"node": "5", "key": "batch_size"},
            "cfg_scale": {"node": "61", "key": "cfg"},
            "sampler": {"node": "61", "key": "sampler_name"},
            "steps": {"node": "61", "key": "steps"},
            "seed": {"node": "61", "key": "seed"},
        },
    },
    "ai_chuangzuo_wenshengtu_dongman_fengge_ponyxl3d": {
        "urls": [],
        "positive": {
            "node": "6",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "7",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "lora": {"node": "101"},
        "params": {
            "width": {"node": "5", "key": "width"},
            "height": {"node": "5", "key": "height"},
            "batch_size": {"node": "5", "key": "batch_size"},
            "cfg_scale": {"node": "61", "key": "cfg"},
            "sampler": {"node": "61", "key": "sampler_name"},
            "steps": {"node": "61", "key": "steps"},
            "seed": {"node": "61", "key": "seed"},
        },
    },
    "ai_chuangzuo_wenshengtu_xieshi_fengge": {
        "urls": [],
        "positive": {
            "node": "6",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": None,
        "lora": {"node": "32"},
        "output": {"node": "9"},
        "params": {
            "width": {"node": "27", "key": "width"},
            "height": {"node": "27", "key": "height"},
            "batch_size": {"node": "27", "key": "batch_size"},
            "cfg_scale": {"node": "33", "key": "cfg"},
            "sampler": {"node": "33", "key": "sampler_name"},
            "steps": {"node": "33", "key": "steps"},
            "seed": {"node": "33", "key": "seed"},
        },
    },
    "tushengtu_fengge_zhuanhuan": {
        "urls": [
            {"field": "img_url", "node": "29", "key": "url"},
        ],
        "positive": {
            "node": "20",
            "key": "prompt",
            "class_type": "CLIPTextEncode",
        },
        "negative": None,
        "params": {
            "width": {"node": "28", "key": "width"},
            "height": {"node": "28", "key": "height"},
            "batch_size": {"node": "28", "key": "batch_size"},
        },
    },
    "ai_chuangzuo_wenshengshipin": {
        "urls": [],
        "positive": {
            "node": "8",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "9",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "lora": {"node": "4"},
        "params": {
            "width": {"node": "10", "key": "width"},
            "height": {"node": "10", "key": "height"},
        },
    },
    "ai_chuangzuo_tushengshipin": {
        "urls": [
            {"field": "img_url", "node": "123", "key": "url"},
        ],
        "positive": {
            "node": "6",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "7",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        # "lora": {"node": "131"}, # 2026.3.9 更新工作流后去掉
        # "lora2": {"node": "132"}, # 2026.3.9 更新工作流后去掉
        "params": {
            "width": {"node": "143", "key": "width"},
            "height": {"node": "143", "key": "height"},
            "frame_count": {"node": "144", "key": "value"},
        },
    },
    "ai_chuangzao_chaoqing_fangda": {
        "urls": [
            {"field": "video_url", "node": "39", "key": "url"},
        ],
        "positive": None,
        "negative": None,
        "params": {
            "max_side": {"node": "36", "key": "value"},
        },
    },
    "ai_chuangzao_chaoqing_fangda_2": {
        "urls": [
            {"field": "video_url", "node": "39", "key": "url"},
        ],
        "positive": None,
        "negative": None,
        "params": {},
    },
    "tushengtu_dongzuo_bianji": {
        "urls": [
            {"field": "source_img1_url", "node": "29", "key": "url"},
            {"field": "source_img2_url", "node": "30", "key": "url"},
        ],
        "positive": None,
        "negative": None,
        "params": {
            "positive_prompt": {"node": "20", "key": "prompt"},
            "negative_prompt": {"node": "21", "key": "prompt"},
            "width": {"node": "28", "key": "width"},
            "height": {"node": "28", "key": "height"},
            "batch_size": {"node": "28", "key": "batch_size"},
        },
    },
    "heibai_zhaoxiufu": {
        "urls": [
            {"field": "img_url", "node": "190", "key": "url"},
        ],
        "positive": None,
        "negative": None,
        "params": {
            "width": {"node": "200", "key": "width"},
            "height": {"node": "200", "key": "height"},
        },
    },
    "tushengtu": {
        "urls": [
            {"field": "img_url", "node": "88", "key": "url"},
        ],
        "positive": {
            "node": "22",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "23",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "params": {
            "width": {"node": "5", "key": "width"},
            "height": {"node": "5", "key": "height"},
            "batch_size": {"node": "5", "key": "batch_size"},
        },
    },
    "shipin_huanyi": {
        "urls": [
            {"field": "first_img_url", "node": "38", "key": "url"},
            {"field": "last_img_url", "node": "39", "key": "url"},
        ],
        "positive": {"node": "7", "key": "text"},
        "negative": {"node": "8", "key": "text"},
        "params": {
            "width": {"node": "44", "key": "value"},
            "height": {"node": "46", "key": "value"},
            "frame_count": {"node": "48", "key": "value"},
        },
    },
    "huanlian": {
        "urls": [
            {"field": "video_url", "node": "1", "key": "url"},
            {"field": "img_url", "node": "7", "key": "url"},
        ],
        "positive": None,
        "negative": None,
        "params": {
            "width": {"node": "9", "key": "width"},
            "height": {"node": "9", "key": "height"},
        },
    },
    "huanlian_2": {
        "urls": [
            {"field": "img1_url", "node": "29", "key": "url"},
            {"field": "img2_url", "node": "30", "key": "url"},
        ],
        "positive": {
            "node": "20",
            "key": "prompt",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "21",
            "key": "prompt",
            "class_type": "CLIPTextEncode",
        },
        "params": {
            "width": {"node": "28", "key": "width"},
            "height": {"node": "28", "key": "height"},
            "batch_size": {"node": "28", "key": "batch_size"},
        },
    },
    "huanzhuang": {
        "urls": [
            {"field": "clothes_img_url", "node": "168", "key": "url"},
            {"field": "people_img_url", "node": "169", "key": "url"},
        ],
        "positive": {
            "node": "23",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "params": {},
    },
    "tushengtu_jubu_tuya": {
        "urls": [
            {"field": "img_url", "node": "26", "key": "url"},
            {"field": "mask_url", "node": "27", "key": "url"},
        ],
        "positive": {
            "node": "23",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": None,
        "params": {},
    },
    "tushengtu_tuya_chonghui": {
        "urls": [
            {"field": "url", "node": "29", "key": "url"},
        ],
        "positive": {
            "node": "20",
            "key": "prompt",
            # "class_type": "CLIPTextEncode",
        },
        # "negative": {
        #     "node": "7",
        #     "key": "text",
        #     "class_type": "CLIPTextEncode",
        # },
        # "params": {
        #     "width": {"node": "5", "key": "width"},
        #     "height": {"node": "5", "key": "height"},
        # },
    },
    "tushengtu_tuya_chonghui_2": {
        "urls": [
            {"field": "img_url", "node": "150", "key": "url"},
        ],
        "positive": {
            "node": "184",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "185",
            "key": "text",
            "class_type": "CLIPTextEncode",
        },
        "params": {},
    },
    "tushengtu_beiying_zhuanhuan": {
        "urls": [
            {"field": "img1_url", "node": "29", "key": "url"},
            {"field": "img2_url", "node": "31", "key": "url"},
        ],
        "positive": {
            "node": "20",
            "key": "prompt",
            "class_type": "CLIPTextEncode",
        },
        "negative": {
            "node": "21",
            "key": "prompt",
            "class_type": "CLIPTextEncode",
        },
        "params": {
            "width": {"node": "28", "key": "width"},
            "height": {"node": "28", "key": "height"},
        },
    },
    "dongzuo_kelong_shengtu": {
        "urls": [
            {"field": "img1_url", "node": "29", "key": "url"},
            {"field": "img2_url", "node": "30", "key": "url"},
        ],
        "positive": {
            "node": "20",
            "key": "prompt",
        },
        "negative": {
            "node": "21",
            "key": "prompt",
        },
        "params": {
            "width": {"node": "28", "key": "width"},
            "height": {"node": "28", "key": "height"},
            "batch_size": {"node": "28", "key": "batch_size"},
        },
    },
    "dongzuo_kelong_shengshipin": {
        "urls": [
            {"field": "source_path", "node": "223", "key": "url"},
            {"field": "target_path", "node": "227", "key": "url"},
        ],
        "positive": {
            "node": "73",
            "key": "text",
        },
        "negative": {
            "node": "74",
            "key": "text",
        },
        "params": {
            "width": {"node": "154", "key": "value"},
            "height": {"node": "155", "key": "value"},
        },
    },
}

_WORKFLOW_CACHE: Dict[str, Dict[str, Any]] = {}


def load_workflow(task_type: str) -> Dict[str, Any]:
    path = frw_workflow_integration_workflow_path.get(task_type)
    if not path:
        raise HTTPException(
            status_code=500, detail=f"Unknown workflow task_type: {task_type}"
        )
    if task_type not in _WORKFLOW_CACHE:
        try:
            with open(path, "r", encoding="utf-8") as f:
                _WORKFLOW_CACHE[task_type] = json.load(f)
        except FileNotFoundError:
            raise HTTPException(
                status_code=500, detail=f"Workflow file not found: {path}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to load workflow {task_type}: {e}"
            )
    return copy.deepcopy(_WORKFLOW_CACHE[task_type])


def _must_get_node(workflow: Dict[str, Any], node_id: str) -> Dict[str, Any]:
    node = workflow.get(str(node_id))
    if not node:
        raise HTTPException(
            status_code=500, detail=f"Workflow node not found: {node_id}"
        )
    return node


def _set_input(workflow: Dict[str, Any], node_id: str, key: str, value: Any):
    if value is None:
        return
    node = _must_get_node(workflow, str(node_id))
    inputs = node.setdefault("inputs", {})
    if key not in inputs:
        raise HTTPException(
            status_code=500, detail=f"Workflow node {node_id} missing input key: {key}"
        )
    inputs[key] = value


def _set_lora(
    workflow: Dict[str, Any], node_id: str, lora_list_str: Optional[str]
) -> None:
    node = _must_get_node(workflow, node_id)

    inputs = node.get("inputs")
    if not isinstance(inputs, dict):
        raise HTTPException(
            status_code=500, detail=f"LoRa nodes are not standardized: {node_id}"
        )

    # 解析 lora_list_str
    lora_entries: List[Dict[str, Any]] = []
    if lora_list_str and lora_list_str.strip():
        try:
            parsed = json.loads(lora_list_str)
            if isinstance(parsed, list):
                lora_entries = parsed
            else:
                lora_entries = []
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(
                status_code=500,
                detail='The lora_list format is incorrect. See: [{"name":"face03_pony.safetensors","strength":0.5}]',
            )

    # 构建 name -> strength 映射
    lora_map = {}
    for entry in lora_entries:
        name = entry.get("name")
        strength = entry.get("strength")
        if isinstance(name, str) and isinstance(strength, (int, float)):
            lora_map[name] = float(strength)

    if not lora_map:
        return  # 无有效 LoRA，不修改

    # 收集已有的 lora_x 字段和已配置的 LoRA 名称
    existing_loras: Dict[str, Dict[str, Any]] = {}
    configured_lora_names = set()

    for key, value in inputs.items():
        if key.startswith("lora_") and isinstance(value, dict):
            existing_loras[key] = value
            if isinstance(value.get("lora"), str):
                configured_lora_names.add(value["lora"])

    # 处理已有的 lora_x 字段：只更新在 lora_map 中的 LoRA
    for key, value in existing_loras.items():
        lora_name = value.get("lora")
        if isinstance(lora_name, str) and lora_name in lora_map:
            value["on"] = True
            value["strength"] = lora_map[lora_name]
        else:
            value["on"] = False

    # 处理未配置的 LoRA：直接新建 lora_x 字段
    unconfigured_loras = [
        name for name in lora_map.keys() if name not in configured_lora_names
    ]

    if unconfigured_loras:
        # 找到最大的 lora_x 编号
        max_lora_index = 0
        for key in existing_loras.keys():
            if key.startswith("lora_"):
                try:
                    index = int(key.split("_")[1])
                    max_lora_index = max(max_lora_index, index)
                except (ValueError, IndexError):
                    pass

        # 为每个未配置的 LoRA 创建新的 lora_x 字段
        for idx, lora_name in enumerate(unconfigured_loras):
            new_index = max_lora_index + 1 + idx
            new_key = f"lora_{new_index}"
            inputs[new_key] = {
                "on": True,
                "lora": lora_name,
                "strength": lora_map[lora_name],
            }


def _validate_and_clamp_dimensions(
    task_type: str, width: Optional[int], height: Optional[int]
) -> tuple[Optional[int], Optional[int]]:
    """
    Validate and clamp width/height based on task_type and model constraints.
    Returns (clamped_width, clamped_height) or (None, None) if not applicable.
    """
    if width is None and height is None:
        return None, None

    workflow_path = frw_workflow_integration_workflow_path.get(task_type, "")

    # Determine constraints based on workflow filename
    if "qwen" in workflow_path.lower():
        min_dim, max_dim = 768, 1920
    elif "flux" in workflow_path.lower():
        min_dim, max_dim = 512, 2048
    elif "wan" in workflow_path.lower():
        min_dim, max_dim = 240, 1920
    elif "xl" in workflow_path.lower() or "ponyxl" in workflow_path.lower():
        min_dim, max_dim = 512, 1280
    else:
        return width, height

    clamped_width = width
    clamped_height = height

    if width is not None:
        clamped_width = max(min_dim, min(width, max_dim))

    if height is not None:
        clamped_height = max(min_dim, min(height, max_dim))

    return clamped_width, clamped_height


def patch_workflow(
    workflow: Dict[str, Any],
    task_type: str,
    **params: Any,
) -> None:
    """
    Patch workflow *strictly* according to WORKFLOW_PATCH_PLAN.
    This function does NOT attempt to guess nodes; it only applies the hardcoded plan.
    """
    plan = WORKFLOW_PATCH_PLAN.get(task_type, {})
    if not plan:
        return

    # Validate and clamp dimensions if present
    width = params.get("width")
    height = params.get("height")
    if width is not None or height is not None:
        clamped_width, clamped_height = _validate_and_clamp_dimensions(
            task_type, width, height
        )
        if clamped_width is not None:
            params["width"] = clamped_width
        if clamped_height is not None:
            params["height"] = clamped_height

    # urls
    for item in plan.get("urls", []):
        field = item["field"]
        _set_input(workflow, item["node"], item["key"], params.get(field))

    # prompts
    pos = plan.get("positive")
    if pos:
        _set_input(workflow, pos["node"], pos["key"], params.get("positive_prompt"))

    neg = plan.get("negative")
    if neg:
        _set_input(workflow, neg["node"], neg["key"], params.get("negative_prompt"))

    # lora
    lora = plan.get("lora")
    if lora:
        _set_lora(workflow, lora["node"], params.get("lora_list"))
    lora = plan.get("lora2")
    if lora:
        _set_lora(workflow, lora["node"], params.get("lora_list"))

    # other params
    for pname, target in (plan.get("params") or {}).items():
        _set_input(workflow, target["node"], target["key"], params.get(pname))


# ---------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------


@router.post(
    "/api/public/manju_shouwei_zhen",
    tags=["frwi"],
    name="漫剧首尾帧",
    include_in_schema=True,
)
async def manju_shouwei_zhen(
    request: Request,
    first_img_url: str = Form(..., description="首图URL"),
    last_img_url: str = Form(..., description="尾图URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=480, description="视频宽度"),
    height: int = Form(default=832, description="视频高度"),
    frame_count: int = Form(default=81, ge=80, description="总帧数"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "manju_shouwei_zhen"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        first_img_url=first_img_url,
        last_img_url=last_img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        frame_count=frame_count,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        first_img_url=first_img_url,
        last_img_url=last_img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        frame_count=frame_count,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/manju_tushengshipin",
    tags=["frwi"],
    name="漫剧图生视频",
    include_in_schema=True,
)
async def manju_tushengshipin(
    request: Request,
    img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=480, description="视频宽度"),
    height: int = Form(default=832, description="视频高度"),
    frame_count: int = Form(default=81, ge=80, description="总帧数"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "manju_tushengshipin"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        frame_count=frame_count,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        frame_count=frame_count,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/manju_tushengtu_1",
    tags=["frwi"],
    name="漫剧图生图1（单人-人脸替换）",
    include_in_schema=True,
)
async def manju_tushengtu_1(
    request: Request,
    img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    model: Literal["qwen", "flux"] = Form(description="模型", default="qwen"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "manju_tushengtu_1_" + model

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        positive_prompt=positive_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        positive_prompt=positive_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/manju_tushengtu_2",
    tags=["frwi"],
    name="漫剧图生图2（双人场景）",
    include_in_schema=True,
)
async def manju_tushengtu_2(
    request: Request,
    female_img_url: str = Form(..., description="URL"),
    male_img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    model: Literal["qwen", "flux"] = Form(description="模型", default="qwen"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "manju_tushengtu_2_" + model

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        female_img_url=female_img_url,
        male_img_url=male_img_url,
        positive_prompt=positive_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        female_img_url=female_img_url,
        male_img_url=male_img_url,
        positive_prompt=positive_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/manju_tushengtu_3",
    tags=["frwi"],
    name="漫剧图生图3（单人-人脸替换-风格迁移）",
    include_in_schema=True,
)
async def manju_tushengtu_3(
    request: Request,
    img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    model: Literal["qwen", "flux"] = Form(description="模型", default="qwen"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "manju_tushengtu_3_" + model

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        positive_prompt=positive_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        positive_prompt=positive_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/manju_tushengtu_4",
    tags=["frwi"],
    name="漫剧图生图4（通用）",
    include_in_schema=True,
)
async def manju_tushengtu_4(
    request: Request,
    img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    model: Literal["qwen", "flux"] = Form(description="模型", default="qwen"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "manju_tushengtu_4_" + model

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        positive_prompt=positive_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        positive_prompt=positive_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/manju_tushengtu_dongman_fengge",
    tags=["frwi"],
    name="漫剧图生图（日式动漫风格）",
    include_in_schema=True,
)
async def manju_tushengtu_dongman_fengge(
    request: Request,
    img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "manju_tushengtu_dongman_fengge"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/manju_wenshengtu_juese_shengcheng",
    tags=["frwi"],
    name="漫剧文生图（角色生成）",
    include_in_schema=True,
)
async def manju_wenshengtu_juese_shengcheng(
    request: Request,
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "manju_wenshengtu_juese_shengcheng"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/ai_chuangzuo_wenshengtu_dongman_fengge",
    tags=["frwi"],
    name="AI创作 --> 文生图 --> 动漫风格",
    include_in_schema=True,
)
async def ai_chuangzuo_wenshengtu_dongman_fengge(
    request: Request,
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    cfg_scale: float = Form(7.0, ge=0, le=30, description="提示词系数"),
    sampler: str = Form("euler", description="采样方法"),
    steps: int = Form(20, ge=1, description="采样步数"),
    seed: int = Form(0, ge=0, description="随机种子"),
    lora_list: str = Form("", description='lora列表([{"name",xxx,"strength":xxx}])'),
    model: Literal["ponyxl", "ponyxl2d", "ponyxl3d"] = Form(
        description="模型", default="ponyxl"
    ),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "ai_chuangzuo_wenshengtu_dongman_fengge"
    task_type = task_type + "_" + model

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        cfg_scale=cfg_scale,
        sampler=sampler,
        steps=steps,
        seed=seed,
        lora_list=lora_list,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        cfg_scale=cfg_scale,
        sampler=sampler,
        steps=steps,
        seed=seed,
        lora_list=lora_list,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/ai_chuangzuo_wenshengtu_xieshi_fengge",
    tags=["frwi"],
    name="AI创作 --> 文生图 --> 写实风格",
    include_in_schema=True,
)
async def ai_chuangzuo_wenshengtu_xieshi_fengge(
    request: Request,
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    cfg_scale: float = Form(1, ge=0, le=30, description="提示词系数"),
    sampler: str = Form("euler", description="采样方法"),
    steps: int = Form(8, ge=1, description="采样步数"),
    seed: int = Form(490136318362856, ge=0, description="随机种子"),
    lora_list: str = Form("", description='lora列表([{"name",xxx,"strength":xxx}])'),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "ai_chuangzuo_wenshengtu_xieshi_fengge"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        cfg_scale=cfg_scale,
        sampler=sampler,
        steps=steps,
        seed=seed,
        lora_list=lora_list,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        cfg_scale=cfg_scale,
        sampler=sampler,
        steps=steps,
        seed=seed,
        lora_list=lora_list,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/tushengtu_fengge_zhuanhuan",
    tags=["frwi"],
    name="图生图 -- 风格转换",
    include_in_schema=True,
)
async def tushengtu_fengge_zhuanhuan(
    request: Request,
    img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "tushengtu_fengge_zhuanhuan"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )
    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/ai_chuangzuo_wenshengshipin",
    tags=["frwi"],
    name="AI 创作 -- 文生视频",
    include_in_schema=True,
)
async def ai_chuangzuo_wenshengshipin(
    request: Request,
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="视频宽度"),
    height: int = Form(default=600, description="视频高度"),
    lora_list: str = Form("", description='lora列表([{"name",xxx,"strength":xxx}])'),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "ai_chuangzuo_wenshengshipin"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        lora_list=lora_list,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        lora_list=lora_list,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/ai_chuangzuo_tushengshipin",
    tags=["frwi"],
    name="AI 创作 -- 图生视频",
    include_in_schema=True,
)
async def ai_chuangzuo_tushengshipin(
    request: Request,
    img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    frame_count: int = Form(default=81, ge=80, description="总帧数"),
    # lora_list: str = Form("", description='lora列表([{"name",xxx,"strength":xxx}])'), # 2026.3.9 更新工作流后去掉
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "ai_chuangzuo_tushengshipin"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        frame_count=frame_count,
        # lora_list=lora_list,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        frame_count=frame_count,
        # lora_list=lora_list,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/ai_chuangzao_chaoqing_fangda",
    tags=["frwi"],
    name="AI 创造 - 超清放大 - 视频",
    include_in_schema=True,
)
async def ai_chuangzao_chaoqing_fangda(
    request: Request,
    video_url: str = Form(..., description="视频URL"),
    # upscale_factor: int = Form(2, ge=1, le=8, description="放大倍数"),
    max_side: int = Form(default=1280, description="最长边"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "ai_chuangzao_chaoqing_fangda"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        video_url=video_url,
        # upscale_factor=upscale_factor,
        max_side=max_side,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        video_url=video_url,
        # upscale_factor=upscale_factor,
        max_side=max_side,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


# @router.post(
#     "/api/public/ai_chuangzao_chaoqing_fangda_2",
#     tags=["frwi"],
#     name="AI 创造 - 超清放大 - 视频(2)",
#     include_in_schema=True,
# )
async def ai_chuangzao_chaoqing_fangda_2(
    request: Request,
    video_url: str = Form(..., description="视频URL"),
    # upscale_factor: int = Form(2, ge=1, le=8, description="放大倍数"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "ai_chuangzao_chaoqing_fangda_2"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        video_url=video_url,
        # upscale_factor=upscale_factor,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        video_url=video_url,
        # upscale_factor=upscale_factor,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/tushengtu_dongzuo_bianji",
    tags=["frwi"],
    name="图生图-动作编辑",
    include_in_schema=True,
)
async def tushengtu_dongzuo_bianji(
    request: Request,
    source_img1_url: str = Form(..., description="URL"),
    source_img2_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    # motion_type: str = Form(..., description="动作类型"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "tushengtu_dongzuo_bianji"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        source_img1_url=source_img1_url,
        source_img2_url=source_img2_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        # motion_type=motion_type,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        source_img1_url=source_img1_url,
        source_img2_url=source_img2_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        # motion_type=motion_type,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/heibai_zhaoxiufu",
    tags=["frwi"],
    name="黑白照修复",
    include_in_schema=True,
)
async def heibai_zhaoxiufu(
    request: Request,
    img_url: str = Form(..., description="URL"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    # upscale_factor: int = Form(2, ge=1, le=8, description="放大倍数"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "heibai_zhaoxiufu"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        width=width,
        height=height,
        # upscale_factor=upscale_factor,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        width=width,
        height=height,
        # upscale_factor=upscale_factor,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/tushengtu",
    tags=["frwi"],
    name="图生图",
    include_in_schema=True,
)
async def tushengtu(
    request: Request,
    img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "tushengtu"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/shipin_huanyi",
    tags=["frwi"],
    name="视频换衣",
    include_in_schema=True,
)
async def shipin_huanyi(
    request: Request,
    first_img_url: str = Form(..., description="首图URL"),
    last_img_url: str = Form(..., description="尾图URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=480, description="视频宽度"),
    height: int = Form(default=832, description="视频高度"),
    frame_count: int = Form(default=81, ge=80, description="总帧数"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "shipin_huanyi"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        first_img_url=first_img_url,
        last_img_url=last_img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        frame_count=frame_count,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        first_img_url=first_img_url,
        last_img_url=last_img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        frame_count=frame_count,
    )

    logger.info(f"Publishing: task_type={task_type}, task_id={task_id}")
    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/huanlian",
    tags=["frwi"],
    name="换脸-视频",
    include_in_schema=True,
)
async def huanlian(
    request: Request,
    video_url: str = Form(..., description="URL"),
    img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=480, description="视频宽度"),
    height: int = Form(default=832, description="视频高度"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "huanlian"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        video_url=video_url,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        video_url=video_url,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/huanlian_2",
    tags=["frwi"],
    name="换脸-图片",
    include_in_schema=True,
)
async def huanlian_2(
    request: Request,
    img1_url: str = Form(..., description="URL"),
    img2_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(1, ge=1, description="图片张数"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "huanlian_2"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img1_url=img1_url,
        img2_url=img2_url,
        width=width,
        height=height,
        batch_size=batch_size,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img1_url=img1_url,
        img2_url=img2_url,
        width=width,
        height=height,
        batch_size=batch_size,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/huanzhuang",
    tags=["frwi"],
    name="换装",
    include_in_schema=True,
)
async def huanzhuang(
    request: Request,
    clothes_img_url: str = Form(..., description="URL"),
    people_img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "huanzhuang"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        clothes_img_url=clothes_img_url,
        people_img_url=people_img_url,
        positive_prompt=positive_prompt,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        clothes_img_url=clothes_img_url,
        people_img_url=people_img_url,
        positive_prompt=positive_prompt,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/tushengtu_jubu_tuya",
    tags=["frwi"],
    name="图生图 -- 局部涂鸦",
    include_in_schema=True,
)
async def tushengtu_jubu_tuya(
    request: Request,
    img_url: str = Form(..., description="URL"),
    mask_url: str = Form(..., description="mask URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "tushengtu_jubu_tuya"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        mask_url=mask_url,
        positive_prompt=positive_prompt,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        mask_url=mask_url,
        positive_prompt=positive_prompt,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/tushengtu_tuya_chonghui",
    tags=["frwi"],
    name="图生图 -- 涂鸦重绘",
    include_in_schema=True,
)
async def tushengtu_tuya_chonghui(
    request: Request,
    img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    # negative_prompt: str = Form(default="", description="反向提示词"),
    # width: int = Form(default=800, description="图片宽度"),
    # height: int = Form(default=600, description="图片高度"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "tushengtu_tuya_chonghui"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        positive_prompt=positive_prompt,
        # negative_prompt=negative_prompt,
        # width=width,
        # height=height,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        positive_prompt=positive_prompt,
        # negative_prompt=negative_prompt,
        # width=width,
        # height=height,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/tushengtu_tuya_chonghui_2",
    tags=["frwi"],
    name="图生图 -- 涂鸦重绘(2)",
    include_in_schema=True,
)
async def tushengtu_tuya_chonghui_2(
    request: Request,
    img_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "tushengtu_tuya_chonghui_2"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img_url=img_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/tushengtu_beiying_zhuanhuan",
    tags=["frwi"],
    name="图生图 -- 背影转换",
    include_in_schema=True,
)
async def tushengtu_beiying_zhuanhuan(
    request: Request,
    img1_url: str = Form(..., description="URL"),
    img2_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(..., description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "tushengtu_beiying_zhuanhuan"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img1_url=img1_url,
        img2_url=img2_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img1_url=img1_url,
        img2_url=img2_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/dongzuo_kelong_shengtu",
    tags=["frwi"],
    name="动作克隆生图",
    include_in_schema=True,
)
async def dongzuo_kelong_shengtu(
    request: Request,
    img1_url: str = Form(..., description="URL"),
    img2_url: str = Form(..., description="URL"),
    positive_prompt: str = Form(None, description="正向提示词"),
    negative_prompt: str = Form(default="", description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    batch_size: int = Form(4, ge=1, description="图片张数"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "dongzuo_kelong_shengtu"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        img1_url=img1_url,
        img2_url=img2_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        img1_url=img1_url,
        img2_url=img2_url,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        batch_size=batch_size,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())


@router.post(
    "/api/public/dongzuo_kelong_shengshipin",
    tags=["frwi"],
    name="动作克隆生视频",
    include_in_schema=True,
)
async def dongzuo_kelong_shengshipin(
    request: Request,
    source_path: str = Form(..., description="图片，源图片"),
    target_path: str = Form(..., description="视频，目标视频"),
    positive_prompt: str = Form(None, description="正向提示词"),
    negative_prompt: str = Form(None, description="反向提示词"),
    width: int = Form(default=800, description="图片宽度"),
    height: int = Form(default=600, description="图片高度"),
    bid: Optional[str] = Form(None, description="业务编号"),
    title: Optional[str] = Form(None, description="标题"),
    notify_url: Optional[str] = Form(None, description="回调地址"),
    hash_key: Optional[str] = Form(None, description="hash key"),
    fee: int = Form(10, ge=0, description="费用"),
    app_id: str = Form("", description="app_id"),
    task_id: Optional[str] = Form(None, description="任务ID，不传自动生成"),
):
    if not task_id:
        task_id = str(uuid4())

    task_type = "dongzuo_kelong_shengshipin"

    document = Document(
        uuid=task_id,
        task_id=task_id,
        task_type=task_type,
        status=TaskStatus.PENDING,
        source_path=source_path,
        target_path=target_path,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        bid=bid if bid else task_id,
        notify_url=notify_url,
        fee=fee,
        app_id=app_id,
        title=title,
        hash_key=hash_key,
    )

    workflow = load_workflow(task_type)
    patch_workflow(
        workflow,
        task_type,
        source_path=source_path,
        target_path=target_path,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
    )

    queue_name = get_queue_by_task_type(task_type)

    logger.info(
        f"Publishing: task_type={task_type}, task_id={task_id}, queue={queue_name}"
    )

    await rabbitmq.publish(
        queue_name=queue_name,
        message=json.dumps(workflow, ensure_ascii=False),
        correlation_id=task_id,
    )

    await storage.save("mqtask", document.to_dict())
    await mongodb2.save("mqtask", document.to_dict())

    return JSONResponse(content=document.to_dict())
