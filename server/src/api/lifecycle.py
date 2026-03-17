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
OpenSandbox 生命周期 API 的路由定义。

本模块定义了 FastAPI 的路由，映射到 OpenAPI 规范中定义的端点。
所有业务逻辑都委托给服务层处理，路由层只负责：
1. 接收和验证请求参数
2. 调用相应的服务方法
3. 返回响应结果

路由组织：
- 沙箱 CRUD 操作：创建、列表、获取、删除沙箱
- 沙箱生命周期操作：暂停、恢复、续期
- 沙箱端点操作：获取访问端点、代理请求

所有端点都支持 X-Request-ID 请求头用于请求追踪。
"""

from typing import List, Optional

import httpx
from fastapi import APIRouter, Header, Query, Request, status
from fastapi.exceptions import HTTPException
from fastapi.responses import Response, StreamingResponse

from src.api.schema import (
    CreateSandboxRequest,
    CreateSandboxResponse,
    Endpoint,
    ErrorResponse,
    ListSandboxesRequest,
    ListSandboxesResponse,
    PaginationRequest,
    RenewSandboxExpirationRequest,
    RenewSandboxExpirationResponse,
    Sandbox,
    SandboxFilter,
)
from src.services.factory import create_sandbox_service

# RFC 2616 第 13.5.1 节定义的逐跳请求头
# 这些请求头不应该被转发到后端服务
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

# 不应该转发给不受信任/内部后端服务的敏感请求头
SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
}

# 初始化路由路由器，标签为 "Sandboxes"
router = APIRouter(tags=["Sandboxes"])

# 根据 config.toml 的配置初始化服务（默认为 docker）
sandbox_service = create_sandbox_service()


# ============================================================================
# 沙箱 CRUD 操作
# ============================================================================

@router.post(
    "/sandboxes",
    response_model=CreateSandboxResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "沙箱创建已接受，异步配置中"},
        400: {"model": ErrorResponse, "description": "请求无效或格式错误"},
        401: {"model": ErrorResponse, "description": "认证凭证缺失或无效"},
        409: {"model": ErrorResponse, "description": "操作与当前状态冲突"},
        500: {"model": ErrorResponse, "description": "发生意外服务器错误"},
    },
)
async def create_sandbox(
    request: CreateSandboxRequest,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID", description="用于追踪的唯一请求标识符"),
) -> CreateSandboxResponse:
    """
    从容器镜像创建沙箱。

    从容器镜像创建新沙箱，支持可选的资源限制、环境变量和元数据。
    沙箱直接从指定的镜像配置，不需要预创建的模板。

    处理流程：
    1. 验证请求参数（入口点、元数据标签、超时时间等）
    2. 生成唯一的沙箱 ID
    3. 拉取容器镜像（如果需要）
    4. 创建并启动容器
    5. 设置过期定时器（如果指定了超时）
    6. 返回沙箱信息

    Args:
        request: 沙箱创建请求，包含镜像、资源限制、入口点等
        x_request_id: 用于追踪的唯一请求标识符（可选，如果省略服务器会生成）

    Returns:
        CreateSandboxResponse: 已接受的沙箱创建请求响应

    Raises:
        HTTPException: 如果沙箱创建调度失败
    """
    return sandbox_service.create_sandbox(request)


# 搜索端点
@router.get(
    "/sandboxes",
    response_model=ListSandboxesResponse,
    responses={
        200: {"description": "沙箱的分页集合"},
        400: {"model": ErrorResponse, "description": "请求无效或格式错误"},
        401: {"model": ErrorResponse, "description": "认证凭证缺失或无效"},
        500: {"model": ErrorResponse, "description": "发生意外服务器错误"},
    },
)
async def list_sandboxes(
    state: Optional[List[str]] = Query(None, description="按生命周期状态过滤，可多次传递以实现 OR 逻辑"),
    metadata: Optional[str] = Query(None, description="用于过滤的任意元数据键值对（URL 编码）"),
    page: int = Query(1, ge=1, description="分页的页码"),
    page_size: int = Query(20, ge=1, le=200, alias="pageSize", description="每页的项目数"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID", description="用于追踪的唯一请求标识符"),
) -> ListSandboxesResponse:
    """
    列出沙箱，支持可选的过滤和分页。

    使用查询参数列出所有沙箱，支持可选的过滤和分页。
    所有过滤条件使用 AND 逻辑，多个 `state` 参数在状态内部使用 OR 逻辑。

    过滤规则：
    - state: 支持多个值，如 ?state=Running&state=Paused 会匹配 Running 或 Paused 的沙箱
    - metadata: URL 编码的查询字符串格式，如 ?metadata=user=alice&project=demo

    分页规则：
    - page: 页码，从 1 开始
    - page_size: 每页项目数，范围 1-200，默认 20

    Args:
        state: 按生命周期状态过滤，可多次传递以实现 OR 逻辑
        metadata: 用于过滤的任意元数据键值对（URL 编码）
        page: 分页的页码
        page_size: 每页的项目数
        x_request_id: 用于追踪的唯一请求标识符（可选，如果省略服务器会生成）

    Returns:
        ListSandboxesResponse: 沙箱的分页列表

    Raises:
        HTTPException: 如果 metadata 格式无效
    """
    # 将 metadata 查询字符串解析为字典
    metadata_dict = {}
    if metadata:
        from urllib.parse import parse_qsl
        try:
            # 解析查询字符串格式：key=value&key2=value2
            # strict_parsing=True 会拒绝格式错误的片段，如 "a=1&broken"
            parsed = parse_qsl(metadata, keep_blank_values=True, strict_parsing=True)
            metadata_dict = dict(parsed)
        except Exception as e:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_METADATA_FORMAT", "message": f"无效的 metadata 格式：{str(e)}"}
            )

    # 构建请求对象
    request = ListSandboxesRequest(
        filter=SandboxFilter(state=state, metadata=metadata_dict if metadata_dict else None),
        pagination=PaginationRequest(page=page, pageSize=page_size)
    )

    import logging
    logger = logging.getLogger(__name__)
    logger.info("ListSandboxes: %s", request.filter)

    # 委托给服务层进行过滤和分页
    return sandbox_service.list_sandboxes(request)


@router.get(
    "/sandboxes/{sandbox_id}",
    response_model=Sandbox,
    responses={
        200: {"description": "沙箱当前状态和元数据"},
        401: {"model": ErrorResponse, "description": "认证凭证缺失或无效"},
        403: {"model": ErrorResponse, "description": "认证用户缺少此操作的权限"},
        404: {"model": ErrorResponse, "description": "请求的资源不存在"},
        500: {"model": ErrorResponse, "description": "发生意外服务器错误"},
    },
)
async def get_sandbox(
    sandbox_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID", description="用于追踪的唯一请求标识符"),
) -> Sandbox:
    """
    根据 ID 获取沙箱。

    返回完整的沙箱信息，包括镜像规格、状态、元数据和时间戳。

    处理流程：
    1. 根据 sandbox_id 查找容器
    2. 解析容器状态并映射到沙箱状态
    3. 提取元数据和配置信息
    4. 返回沙箱对象

    Args:
        sandbox_id: 沙箱唯一标识符
        x_request_id: 用于追踪的唯一请求标识符（可选，如果省略服务器会生成）

    Returns:
        Sandbox: 完整的沙箱信息

    Raises:
        HTTPException: 如果沙箱未找到或访问被拒绝
    """
    # 委托给服务层进行沙箱查找
    return sandbox_service.get_sandbox(sandbox_id)


@router.delete(
    "/sandboxes/{sandbox_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "沙箱成功删除"},
        401: {"model": ErrorResponse, "description": "认证凭证缺失或无效"},
        403: {"model": ErrorResponse, "description": "认证用户缺少此操作的权限"},
        404: {"model": ErrorResponse, "description": "请求的资源不存在"},
        409: {"model": ErrorResponse, "description": "操作与当前状态冲突"},
        500: {"model": ErrorResponse, "description": "发生意外服务器错误"},
    },
)
async def delete_sandbox(
    sandbox_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID", description="用于追踪的唯一请求标识符"),
) -> Response:
    """
    删除沙箱。

    终止沙箱执行。沙箱将通过 Stopping 状态转换到 Terminated。

    处理流程：
    1. 查找沙箱容器
    2. 停止容器（如果正在运行）
    3. 删除容器
    4. 清理相关资源（sidecar、OSSFS 挂载等）
    5. 取消过期定时器

    Args:
        sandbox_id: 沙箱唯一标识符
        x_request_id: 用于追踪的唯一请求标识符（可选，如果省略服务器会生成）

    Returns:
        Response: 204 No Content

    Raises:
        HTTPException: 如果沙箱未找到或删除失败
    """
    # 委托给服务层进行删除
    sandbox_service.delete_sandbox(sandbox_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================================
# 沙箱生命周期操作
# ============================================================================

@router.post(
    "/sandboxes/{sandbox_id}/pause",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "暂停操作已接受"},
        401: {"model": ErrorResponse, "description": "认证凭证缺失或无效"},
        403: {"model": ErrorResponse, "description": "认证用户缺少此操作的权限"},
        404: {"model": ErrorResponse, "description": "请求的资源不存在"},
        409: {"model": ErrorResponse, "description": "操作与当前状态冲突"},
        500: {"model": ErrorResponse, "description": "发生意外服务器错误"},
    },
)
async def pause_sandbox(
    sandbox_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID", description="用于追踪的唯一请求标识符"),
) -> Response:
    """
    暂停执行但保留状态。

    暂停运行中的沙箱，同时保留其状态。
    轮询 GET /sandboxes/{sandboxId} 跟踪状态转换到 Paused。

    处理流程：
    1. 查找沙箱容器
    2. 验证容器处于 Running 状态
    3. 调用 Docker pause 命令暂停容器
    4. 返回 202 Accepted

    Args:
        sandbox_id: 沙箱唯一标识符
        x_request_id: 用于追踪的唯一请求标识符（可选，如果省略服务器会生成）

    Returns:
        Response: 202 Accepted

    Raises:
        HTTPException: 如果沙箱未找到或无法暂停
    """
    # 委托给服务层进行暂停编排
    sandbox_service.pause_sandbox(sandbox_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/sandboxes/{sandbox_id}/resume",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "恢复操作已接受"},
        401: {"model": ErrorResponse, "description": "认证凭证缺失或无效"},
        403: {"model": ErrorResponse, "description": "认证用户缺少此操作的权限"},
        404: {"model": ErrorResponse, "description": "请求的资源不存在"},
        409: {"model": ErrorResponse, "description": "操作与当前状态冲突"},
        500: {"model": ErrorResponse, "description": "发生意外服务器错误"},
    },
)
async def resume_sandbox(
    sandbox_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID", description="用于追踪的唯一请求标识符"),
) -> Response:
    """
    恢复暂停的沙箱。

    恢复已暂停沙箱的执行。
    轮询 GET /sandboxes/{sandboxId} 跟踪状态转换到 Running。

    处理流程：
    1. 查找沙箱容器
    2. 验证容器处于 Paused 状态
    3. 调用 Docker unpause 命令恢复容器
    4. 返回 202 Accepted

    Args:
        sandbox_id: 沙箱唯一标识符
        x_request_id: 用于追踪的唯一请求标识符（可选，如果省略服务器会生成）

    Returns:
        Response: 202 Accepted

    Raises:
        HTTPException: 如果沙箱未找到或无法恢复
    """
    # 委托给服务层进行恢复编排
    sandbox_service.resume_sandbox(sandbox_id)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/sandboxes/{sandbox_id}/renew-expiration",
    response_model=RenewSandboxExpirationResponse,
    response_model_exclude_none=True,
    responses={
        200: {"description": "沙箱过期时间成功更新"},
        400: {"model": ErrorResponse, "description": "请求无效或格式错误"},
        401: {"model": ErrorResponse, "description": "认证凭证缺失或无效"},
        403: {"model": ErrorResponse, "description": "认证用户缺少此操作的权限"},
        404: {"model": ErrorResponse, "description": "请求的资源不存在"},
        409: {"model": ErrorResponse, "description": "操作与当前状态冲突"},
        500: {"model": ErrorResponse, "description": "发生意外服务器错误"},
    },
)
async def renew_sandbox_expiration(
    sandbox_id: str,
    request: RenewSandboxExpirationRequest,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID", description="用于追踪的唯一请求标识符"),
) -> RenewSandboxExpirationResponse:
    """
    续期沙箱过期时间。

    续期沙箱的绝对过期时间。
    新的过期时间必须是将来的时间，并且必须在当前 expiresAt 时间之后。

    处理流程：
    1. 查找沙箱容器
    2. 验证新的过期时间有效（将来时间，晚于当前过期时间）
    3. 更新容器标签中的过期时间
    4. 取消旧的过期定时器，设置新的定时器
    5. 返回新的过期时间

    Args:
        sandbox_id: 沙箱唯一标识符
        request: 续期请求，包含新的过期时间
        x_request_id: 用于追踪的唯一请求标识符（可选，如果省略服务器会生成）

    Returns:
        RenewSandboxExpirationResponse: 更新后的过期时间

    Raises:
        HTTPException: 如果沙箱未找到或续期失败
    """
    # 委托给服务层进行过期时间更新
    return sandbox_service.renew_expiration(sandbox_id, request)


# ============================================================================
# 沙箱端点
# ============================================================================

@router.get(
    "/sandboxes/{sandbox_id}/endpoints/{port}",
    response_model=Endpoint,
    response_model_exclude_none=True,
    responses={
        200: {"description": "成功获取端点"},
        401: {"model": ErrorResponse, "description": "认证凭证缺失或无效"},
        403: {"model": ErrorResponse, "description": "认证用户缺少此操作的权限"},
        404: {"model": ErrorResponse, "description": "请求的资源不存在"},
        500: {"model": ErrorResponse, "description": "发生意外服务器错误"},
    },
)
async def get_sandbox_endpoint(
    request: Request,
    sandbox_id: str,
    port: int,
    use_server_proxy: bool = Query(False, description="是否返回服务器代理的 URL"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID", description="用于追踪的唯一请求标识符"),
) -> Endpoint:
    """
    获取沙箱访问端点。

    返回用于访问沙箱内特定端口上运行服务的公共访问端点 URL。
    沙箱内的服务必须在指定端口上监听，端点才可用。

    端点解析逻辑：
    - 如果 use_server_proxy=false（默认）：返回沙箱的直接访问端点
    - 如果 use_server_proxy=true：返回服务器代理 URL，格式为 {base_url}/sandboxes/{sandbox_id}/proxy/{port}

    Args:
        request: FastAPI 请求对象
        sandbox_id: 沙箱唯一标识符
        port: 沙箱内服务监听的端口号（1-65535）
        use_server_proxy: 是否返回服务器代理的 URL
        x_request_id: 用于追踪的唯一请求标识符（可选，如果省略服务器会生成）

    Returns:
        Endpoint: 公共端点 URL

    Raises:
        HTTPException: 如果沙箱未找到或端点不可用
    """
    # 委托给服务层进行端点解析
    endpoint = sandbox_service.get_endpoint(sandbox_id, port)

    if use_server_proxy:
        # 构建代理 URL
        base_url = str(request.base_url).rstrip("/")
        base_url = base_url.replace("https://", "").replace("http://", "")
        endpoint.endpoint = f"{base_url}/sandboxes/{sandbox_id}/proxy/{port}"

    return endpoint


@router.api_route(
    "/sandboxes/{sandbox_id}/proxy/{port}/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def proxy_sandbox_endpoint_request(request: Request, sandbox_id: str, port: int, full_path: str):
    """
    服务器代理端点请求。

    接收所有传入请求，从路径参数确定目标沙箱，
    并异步将请求代理到沙箱。

    代理流程：
    1. 从路径参数提取 sandbox_id 和 port
    2. 获取沙箱的内部端点
    3. 构建目标 URL
    4. 过滤请求头（移除逐跳请求头和敏感请求头）
    5. 转发请求到沙箱
    6. 流式返回响应

    不支持 WebSocket 升级请求。

    Args:
        request: 原始 HTTP 请求
        sandbox_id: 沙箱唯一标识符
        port: 沙箱内服务端口
        full_path: 代理的路径
    """

    # 获取沙箱端点（内部解析模式）
    endpoint = sandbox_service.get_endpoint(sandbox_id, port, resolve_internal=True)

    # 目标主机
    target_host = endpoint.endpoint
    # 查询字符串
    query_string = request.url.query
    # 构建目标 URL
    target_url = (
        f"http://{target_host}/{full_path}?{query_string}"
        if query_string
        else f"http://{target_host}/{full_path}"
    )

    # 获取 httpx 客户端
    client: httpx.AsyncClient = request.app.state.http_client

    try:
        # 检查 Upgrade 头，不支持 WebSocket
        upgrade_header = request.headers.get("Upgrade", "")
        if upgrade_header.lower() == "websocket":
            raise HTTPException(status_code=400, detail="暂不支持 WebSocket 升级")

        # 过滤请求头
        hop_by_hop = set(HOP_BY_HOP_HEADERS)
        # 处理 Connection 头中指定的额外逐跳头
        connection_header = request.headers.get("connection")
        if connection_header:
            hop_by_hop.update(
                header.strip().lower()
                for header in connection_header.split(",")
                if header.strip()
            )
        # 构建转发请求头
        headers = {}
        for key, value in request.headers.items():
            key_lower = key.lower()
            # 跳过 Host、逐跳头和敏感头
            if (
                key_lower != "host"
                and key_lower not in hop_by_hop
                and key_lower not in SENSITIVE_HEADERS
            ):
                headers[key] = value

        # 构建请求
        req = client.build_request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=request.stream(),
        )

        # 发送请求并获取响应
        resp = await client.send(req, stream=True)

        # 过滤响应头
        hop_by_hop = set(HOP_BY_HOP_HEADERS)
        connection_header = resp.headers.get("connection")
        if connection_header:
            hop_by_hop.update(
                header.strip().lower()
                for header in connection_header.split(",")
                if header.strip()
            )
        response_headers = {
            key: value
            for key, value in resp.headers.items()
            if key.lower() not in hop_by_hop
        }

        # 返回流式响应
        return StreamingResponse(
            content=resp.aiter_bytes(),
            status_code=resp.status_code,
            headers=response_headers,
        )
    except httpx.ConnectError as e:
        # 无法连接到后端沙箱
        raise HTTPException(
            status_code=502,
            detail=f"无法连接到后端沙箱 {endpoint}: {e}",
        )
    except HTTPException:
        # 保留显式的 HTTP 异常（如上面抛出的 WebSocket 不支持错误）
        raise
    except Exception as e:
        # 代理中发生的其他内部错误
        raise HTTPException(
            status_code=500, detail=f"代理中发生内部错误：{e}"
        )
