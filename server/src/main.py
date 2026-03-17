# Copyright 2025 Alibaba Group Holding Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
FastAPI 应用程序入口点，OpenSandbox 生命周期 API 的主模块。

本模块初始化 FastAPI 应用程序，包括：
1. 配置加载：从配置文件加载应用配置
2. 日志配置：统一日志格式，支持请求追踪
3. 中间件注册：认证、CORS、请求 ID 等中间件
4. 路由注册：API 路由注册
5. 异常处理：统一异常处理格式
6. 生命周期管理：应用启动和关闭时的资源管理

应用架构：
- 配置层 (config.py): 配置管理和验证
- 中间件层 (middleware/): 请求处理中间件
- 路由层 (api/lifecycle.py): API 端点定义
- 服务层 (services/): 业务逻辑实现
- 运行时层 (services/docker.py, services/k8s/): 容器运行时抽象

日志系统：
- 使用 uvicorn 的日志配置作为基础
- 添加 request_id 过滤器，支持请求追踪
- 统一日志格式：%(levelprefix)s %(asctime)s [%(request_id)s] %(name)s: %(message)s
- 支持彩色日志输出

中间件执行顺序（从外到内）：
1. RequestIdMiddleware: 生成/传递请求 ID
2. CORSMiddleware: 跨域资源共享
3. AuthMiddleware: API 认证

启动流程：
1. 加载配置
2. 配置日志
3. 创建 lifespan 上下文管理器
4. 注册中间件
5. 注册路由
6. 注册异常处理器
"""

import copy
import logging.config
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import load_config
from uvicorn.config import LOGGING_CONFIG as UVICORN_LOGGING_CONFIG

# 在初始化路由/中间件之前加载配置
# 这是必要的，因为中间件和路由可能需要配置信息
app_config = load_config()

# 统一日志格式（包括 uvicorn 访问/错误日志），带时间戳前缀
# 复制 uvicorn 默认日志配置，避免修改全局配置
_log_config = copy.deepcopy(UVICORN_LOGGING_CONFIG)
# 日志格式：级别前缀 | 时间戳 | [请求 ID] | 记录器名称 | 消息
_fmt = "%(levelprefix)s %(asctime)s [%(request_id)s] %(name)s: %(message)s"
# 日期格式：年 - 月-日 时：分：秒 + 时区
_datefmt = "%Y-%m-%d %H:%M:%S%z"

# 将 request_id 注入到日志记录中，以便关联一个请求的所有日志
# RequestIdFilter 从请求上下文中提取 request_id 并添加到日志记录
_log_config["filters"] = {
    "request_id": {"()": "src.middleware.request_id.RequestIdFilter"},
}
# 为默认处理器和访问日志处理器启用 request_id 过滤器
_log_config["handlers"]["default"]["filters"] = ["request_id"]
_log_config["handlers"]["access"]["filters"] = ["request_id"]

# 启用颜色，并为默认日志器和访问日志器设置格式
_log_config["formatters"]["default"]["fmt"] = _fmt
_log_config["formatters"]["default"]["datefmt"] = _datefmt
_log_config["formatters"]["default"]["use_colors"] = True

_log_config["formatters"]["access"]["fmt"] = _fmt
_log_config["formatters"]["access"]["datefmt"] = _datefmt
_log_config["formatters"]["access"]["use_colors"] = True

# 确保项目记录器 (src.*) 使用配置的级别通过默认处理器发出日志
# 这确保应用日志使用统一的格式和过滤器
_log_config["loggers"]["src"] = {
    "handlers": ["default"],
    "level": app_config.server.log_level.upper(),
    "propagate": False,
}

# 应用日志配置
logging.config.dictConfig(_log_config)
# 设置根日志级别
logging.getLogger().setLevel(
    getattr(logging, app_config.server.log_level.upper(), logging.INFO)
)

# 在配置日志后导入路由和中间件，避免循环导入
# E402 忽略：模块级导入在文件顶部，但需要在配置加载后导入
from src.api.lifecycle import router  # noqa: E402
from src.middleware.auth import AuthMiddleware  # noqa: E402
from src.middleware.request_id import RequestIdMiddleware  # noqa: E402
from src.services.runtime_resolver import (  # noqa: E402
    validate_secure_runtime_on_startup,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 应用生命周期管理器。

    管理应用启动和关闭时的资源：
    - 启动时：创建 http 客户端，验证安全运行时配置，创建沙箱服务
    - 关闭时：关闭 http 客户端

    启动流程：
    1. 创建 httpx 异步客户端，用于 HTTP 请求（如代理请求）
    2. 根据配置类型创建相应的客户端（Docker 或 Kubernetes）
    3. 验证安全运行时配置（如 gVisor、Kata、Firecracker）
    4. 创建沙箱服务实例

    Args:
        app: FastAPI 应用实例

    Yields:
        None: 在应用运行期间保持活跃

    Raises:
        Exception: 如果安全运行时验证失败
    """
    # 创建 httpx 异步客户端，超时设置为 180 秒
    # 用于服务器代理功能，将请求转发到沙箱
    app.state.http_client = httpx.AsyncClient(timeout=180.0)

    # 启动时验证安全运行时配置
    try:
        # 根据配置确定创建哪种运行时客户端
        docker_client = None
        k8s_client = None
        runtime_type = app_config.runtime.type

        if runtime_type == "docker":
            import docker

            # 从环境变量创建 Docker 客户端
            docker_client = docker.from_env()
            logger.info("正在验证 Docker 后端的安全运行时配置")
        elif runtime_type == "kubernetes":
            from src.services.k8s.client import K8sClient

            # 创建 Kubernetes 客户端
            k8s_client = K8sClient(app_config.kubernetes)
            logger.info("正在验证 Kubernetes 后端的安全运行时配置")

        # 验证安全运行时配置
        # 这会检查必要的运行时组件是否正确配置和可用
        await validate_secure_runtime_on_startup(
            app_config,
            docker_client=docker_client,
            k8s_client=k8s_client,
        )

        # 验证通过后创建沙箱服务
        from src.services.factory import create_sandbox_service

        app.state.sandbox_service = create_sandbox_service()
    except Exception as exc:
        logger.error("安全运行时验证失败：%s", exc)
        raise

    # 应用运行期间
    yield

    # 应用关闭时清理资源
    await app.state.http_client.aclose()


# 初始化 FastAPI 应用
app = FastAPI(
    title="OpenSandbox 生命周期 API",
    version="0.1.0",
    description="沙箱生命周期 API 协调不可信工作负载的创建、执行、暂停、恢复和最终销毁",
    docs_url="/docs",       # Swagger UI 文档路径
    redoc_url="/redoc",     # ReDoc 文档路径
    lifespan=lifespan,      # 生命周期管理器
)

# 附加全局配置供运行时访问
# 其他模块可以通过 request.app.state.config 访问配置
app.state.config = app_config

# 中间件按添加顺序的逆序执行：最后添加的 = 最先执行（最外层）
# 先添加认证和 CORS，这样它们在 RequestIdMiddleware 之后执行
app.add_middleware(AuthMiddleware, config=app_config)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # 允许所有来源
    allow_credentials=True,   # 允许凭证
    allow_methods=["*"],      # 允许所有方法
    allow_headers=["*"],      # 允许所有头
)
# RequestIdMiddleware 最后添加 = 最外层：最先运行，这样每个响应（包括
# 来自 AuthMiddleware 的 401）都会获得 X-Request-ID，日志在上下文中有 request_id
app.add_middleware(RequestIdMiddleware)

# 在根路径和版本化前缀处包含 API 路由
# 这样 API 既可以通过 /sandboxes 访问，也可以通过 /v1/sandboxes 访问
app.include_router(router)
app.include_router(router, prefix="/v1")

# 默认错误代码和消息
DEFAULT_ERROR_CODE = "GENERAL::UNKNOWN_ERROR"
DEFAULT_ERROR_MESSAGE = "发生意外错误。"


def _normalize_error_detail(detail: Any) -> dict[str, str]:
    """
    确保 HTTP 错误始终符合统一的错误响应格式 {"code": "...", "message": "..."}。

    FastAPI 的 HTTPException detail 可以是字符串、字典或其他类型。
    此函数将所有类型统一为标准格式。

    Args:
        detail: HTTPException 的 detail 参数，可以是任何类型

    Returns:
        dict[str, str]: 标准化的错误响应字典，包含 code 和 message
    """
    if isinstance(detail, dict):
        # detail 已经是字典，提取 code 和 message
        code = detail.get("code") or DEFAULT_ERROR_CODE
        message = detail.get("message") or DEFAULT_ERROR_MESSAGE
        return {"code": code, "message": message}
    # detail 不是字典，转换为字符串作为 message
    message = str(detail) if detail else DEFAULT_ERROR_MESSAGE
    return {"code": DEFAULT_ERROR_CODE, "message": message}


@app.exception_handler(HTTPException)
async def sandbox_http_exception_handler(request: Request, exc: HTTPException):
    """
    将 FastAPI HTTPException 负载扁平化为标准错误格式。

    FastAPI 默认的错误响应格式可能与 API 规范不一致。
    此处理器确保所有 HTTP 异常都返回统一的错误格式。

    Args:
        request: 原始请求对象
        exc: HTTPException 异常实例

    Returns:
        JSONResponse: 标准化错误响应的 JSON 响应
    """
    # 标准化错误详情
    content = _normalize_error_detail(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=exc.headers,
    )


@app.get("/health")
async def health_check():
    """
    健康检查端点。

    用于 Kubernetes 或其他编排系统的健康检查。
    简单的 GET 请求，返回健康状态。

    Returns:
        dict: 健康状态字典 {"status": "healthy"}
    """
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    # 运行应用程序
    # 使用 uvicorn 直接运行，支持热重载
    uvicorn.run(
        "src.main:app",              # 应用模块路径
        host=app_config.server.host,  # 从配置读取主机
        port=app_config.server.port,  # 从配置读取端口
        reload=True,                  # 启用热重载（开发模式）
        log_config=_log_config,       # 使用自定义日志配置
    )
