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
OpenSandbox 生命周期 API 的 Pydantic 数据模型定义。

本模块定义了所有 API 请求和响应使用的数据模型，基于 OpenAPI 规范。
这些模型用于：
1. 请求数据验证：确保客户端发送的数据符合预期格式
2. 响应数据序列化：确保服务器返回的数据格式一致
3. API 文档生成：FastAPI 使用这些模型自动生成 OpenAPI 文档

模型分类：
- 镜像规格（ImageSpec）：定义容器镜像及其认证信息
- 资源限制（ResourceLimits）：定义 CPU、内存等资源约束
- 网络策略（NetworkPolicy）：定义出站网络访问规则
- 卷配置（Volume）：定义存储挂载配置，支持多种后端类型
- 沙箱模型（Sandbox）：沙箱的完整表示
- 沙箱状态（SandboxStatus）：沙箱的生命周期状态
- 列表和分页（ListSandboxesRequest/Response）：分页查询相关
- 过期时间管理（RenewSandboxExpirationRequest/Response）：续期相关
- 端点（Endpoint）：沙箱服务访问端点
- 错误响应（ErrorResponse）：统一错误响应格式
"""

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, RootModel, model_validator


# ============================================================================
# 镜像规格（Image Specification）
# ============================================================================

class ImageAuth(BaseModel):
    """
    私有容器注册表的认证凭证。

    当使用需要认证的私有容器镜像时，需要提供用户名和密码。
    这些信息会在拉取镜像时传递给 Docker 或 Kubernetes。

    Attributes:
        username: 注册表用户名或服务账户名
        password: 注册表密码或认证令牌（如访问令牌）
    """
    username: str = Field(..., description="注册表用户名或服务账户")
    password: str = Field(..., description="注册表密码或认证令牌")


class ImageSpec(BaseModel):
    """
    沙箱配置的容器镜像规格。

    支持两种镜像来源：
    1. 公共注册表镜像：如 "python:3.11"、"nginx:latest"，无需认证
    2. 私有注册表镜像：如 "gcr.io/my-project/app:v1.0"，需要提供 auth 认证信息

    Examples:
        # 公共镜像
        ImageSpec(uri="python:3.11")

        # 私有镜像
        ImageSpec(
            uri="gcr.io/my-project/app:v1.0",
            auth=ImageAuth(username="my-user", password="my-token")
        )

    Attributes:
        uri: 容器镜像 URI，使用标准格式（如 'python:3.11'、'gcr.io/my-project/app:v1.0'）
        auth: 注册表认证凭证（私有注册表必需）
    """
    uri: str = Field(
        ...,
        description="容器镜像 URI，使用标准格式（如 'python:3.11'、'gcr.io/my-project/app:v1.0'）",
    )
    auth: Optional[ImageAuth] = Field(
        None,
        description="注册表认证凭证（私有注册表必需）",
    )


# ============================================================================
# 资源限制（Resource Limits）
# ============================================================================

class ResourceLimits(RootModel[Dict[str, str]]):
    """
    运行时资源约束，以键值对形式定义。

    类似于 Kubernetes 的资源规格定义，允许灵活地定义各种资源限制。
    常见的资源类型包括：
    - cpu: CPU 限制，支持毫核（如 "500m" 表示 0.5 核）或整数核（如 "2" 表示 2 核）
    - memory: 内存限制，支持 Mi（如 "512Mi"）或 Gi（如 "2Gi"）
    - gpu: GPU 数量（如 "1" 表示 1 个 GPU）

    Examples:
        ResourceLimits({"cpu": "500m", "memory": "512Mi"})
        ResourceLimits({"cpu": "2", "memory": "4Gi", "gpu": "1"})

    Attributes:
        root: 资源键值对字典，如 {"cpu": "500m", "memory": "512Mi", "gpu": "1"}
    """
    root: Dict[str, str] = Field(
        default_factory=dict,
        example={"cpu": "500m", "memory": "512Mi", "gpu": "1"},
    )


class NetworkRule(BaseModel):
    """
    出站网络规则：允许或拒绝特定的域名或通配符。

    用于控制沙箱可以访问的外部网络资源。每条规则包含：
    - action: allow（允许）或 deny（拒绝）
    - target: 目标域名，支持通配符（如 "*.example.com"）

    Examples:
        # 允许访问特定域名
        NetworkRule(action="allow", target="api.github.com")

        # 拒绝访问特定域名
        NetworkRule(action="deny", target="malicious-site.com")

        # 允许访问所有子域名
        NetworkRule(action="allow", target="*.googleapis.com")

    Attributes:
        action: 对匹配目标执行的操作（allow | deny）
        target: 完全限定域名（FQDN）或通配符域名（如 'example.com'、'*.example.com'）
    """

    action: str = Field(..., description="对匹配目标执行的操作（allow | deny）")
    target: str = Field(
        ...,
        description="完全限定域名或通配符域名（如 'example.com'、'*.example.com'）",
        min_length=1,
    )

    class Config:
        populate_by_name = True


class NetworkPolicy(BaseModel):
    """
    出站网络策略，匹配 sidecar /policy 端点的有效负载格式。

    用于定义沙箱的出站网络访问控制策略。包含：
    - default_action: 当没有规则匹配时的默认操作（allow 或 deny），默认为 deny
    - egress: 有序的出站规则列表，空列表或未设置表示允许所有出站流量

    Examples:
        # 默认拒绝，只允许特定域名
        NetworkPolicy(
            default_action="deny",
            egress=[
                NetworkRule(action="allow", target="api.github.com"),
                NetworkRule(action="allow", target="*.googleapis.com"),
            ]
        )

    Attributes:
        default_action: 当没有出站规则匹配时的默认操作（allow | deny），
                        如果省略，sidecar 默认为 deny
        egress: 有序的出站规则列表，空列表或未设置表示启动时允许所有
    """

    default_action: Optional[str] = Field(
        default=None,
        alias="defaultAction",
        description="当没有出站规则匹配时的默认操作（allow | deny），如果省略，sidecar 默认为 deny",
    )
    egress: list[NetworkRule] = Field(
        default_factory=list,
        description="有序的出站规则列表，空列表或未设置表示启动时允许所有",
    )

    class Config:
        populate_by_name = True


# ============================================================================
# 卷配置（Volume Definitions）
# ============================================================================


class Host(BaseModel):
    """
    主机路径绑定挂载后端。

    将主机文件系统上的目录挂载到容器中。
    仅在运行时支持主机挂载时可用。

    安全说明：主机路径受服务器端允许列表限制。
    用户必须指定在允许前缀下的路径。

    Examples:
        Host(path="/data/opensandbox/user1")

    Attributes:
        path: 主机文件系统上要挂载的绝对路径
    """

    path: str = Field(
        ...,
        description="主机文件系统上要挂载的绝对路径",
        pattern=r"^(/|[A-Za-z]:[\\/])",
    )


class PVC(BaseModel):
    """
    平台管理的命名卷后端。

    一种运行时中立的抽象，用于引用预先存在的、平台管理的命名卷。
    在所有运行时中的语义相同：通过名称声明现有卷，将其挂载到容器中，
    并将卷生命周期管理交给用户。

    - Kubernetes: 映射到同一命名空间中的 PersistentVolumeClaim
    - Docker: 映射到 Docker 命名卷（通过 `docker volume create` 创建）

    Examples:
        # Kubernetes PVC
        PVC(claim_name="my-data-pvc")

        # Docker 命名卷
        PVC(claim_name="my-docker-volume")

    Attributes:
        claim_name: 目标平台上的卷名称，在 Kubernetes 中是 PVC 名称，在 Docker 中是命名卷名称
    """

    claim_name: str = Field(
        ...,
        alias="claimName",
        description=(
            "目标平台上的卷名称。"
            "在 Kubernetes 中这是 PVC 名称；在 Docker 中这是命名卷名称。"
        ),
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
        max_length=253,
    )

    class Config:
        populate_by_name = True


class OSSFS(BaseModel):
    """
    通过 ossfs 实现的阿里云 OSS 挂载后端。

    运行时将主机端的 OSS 路径挂载到 `storage.ossfs_mount_root` 下，
    然后将解析后的路径绑定挂载到沙箱容器中。
    通过 `Volume.subPath` 选择前缀。

    在 Docker 运行时中，OSSFS 后端需要运行在支持 FUSE 的 Linux 主机上。

    Examples:
        # 基本 OSS 挂载
        OSSFS(
            bucket="my-bucket",
            endpoint="oss-cn-hangzhou.aliyuncs.com",
            access_key_id="LTAI...",
            access_key_secret="..."
        )

        # 带额外挂载选项
        OSSFS(
            bucket="my-bucket",
            endpoint="oss-cn-hangzhou.aliyuncs.com",
            access_key_id="LTAI...",
            access_key_secret="...",
            options=["allow_other", "max_stat_cache=10000"]
        )

    Attributes:
        bucket: OSS 存储桶名称
        endpoint: OSS 端点，如 'oss-cn-hangzhou.aliyuncs.com'
        version: ossfs 主版本号，运行时挂载集成使用（"1.0" 或 "2.0"）
        options: 额外的 ossfs 挂载选项，运行时根据版本编码选项：
                 1.0 => 'ossfs ... -o <option>', 2.0 => 'ossfs2 config line --<option>'
                 提供原始选项负载，不带前导 '-'
        access_key_id: 内联凭证模式的 OSS 访问密钥 ID
        access_key_secret: 内联凭证模式的 OSS 访问密钥密钥
    """

    bucket: str = Field(
        ...,
        description="OSS 存储桶名称",
        min_length=3,
        max_length=63,
    )
    endpoint: str = Field(
        ...,
        description="OSS 端点，如 'oss-cn-hangzhou.aliyuncs.com'",
        min_length=1,
    )
    version: Literal["1.0", "2.0"] = Field(
        "2.0",
        description="ossfs 主版本号，运行时挂载集成使用",
    )
    options: Optional[List[str]] = Field(
        None,
        description=(
            "额外的 ossfs 挂载选项。运行时根据版本编码选项："
            "1.0 => 'ossfs ... -o <option>', 2.0 => 'ossfs2 config line --<option>'。"
            "提供原始选项负载，不带前导 '-'。"
        ),
    )
    access_key_id: Optional[str] = Field(
        None,
        alias="accessKeyId",
        description="内联凭证模式的 OSS 访问密钥 ID",
        min_length=1,
    )
    access_key_secret: Optional[str] = Field(
        None,
        alias="accessKeySecret",
        description="内联凭证模式的 OSS 访问密钥密钥",
        min_length=1,
    )
    class Config:
        populate_by_name = True

    @model_validator(mode="after")
    def validate_inline_credentials(self) -> "OSSFS":
        """
        验证内联凭证是否正确提供。

        对于当前 OSSFS 模式，必须同时提供 access_key_id 和 access_key_secret。

        Returns:
            self: 验证通过的 OSSFS 实例

        Raises:
            ValueError: 如果缺少任何一个凭证字段
        """
        if not self.access_key_id or not self.access_key_secret:
            raise ValueError(
                "OSSFS 内联凭证是必需的：需要提供 accessKeyId 和 accessKeySecret。"
            )
        return self


class Volume(BaseModel):
    """
    沙箱的存储挂载定义。

    每个卷条目包含：
    - name: 唯一标识符，用于在沙箱内引用此卷
    - 恰好一个后端结构（host、pvc、ossfs 等），包含特定于后端的字段
    - mount_path: 容器内的挂载点绝对路径
    - read_only: 是否只读挂载
    - sub_path: 可选的后端路径下的子目录

    Examples:
        # 主机路径挂载
        Volume(
            name="data",
            host=Host(path="/data/user1"),
            mount_path="/app/data",
            read_only=True
        )

        # PVC 挂载
        Volume(
            name="persistent-data",
            pvc=PVC(claim_name="my-pvc"),
            mount_path="/app/data",
            sub_path="subdir"
        )

        # OSSFS 挂载
        Volume(
            name="oss-data",
            ossfs=OSSFS(
                bucket="my-bucket",
                endpoint="oss-cn-hangzhou.aliyuncs.com",
                access_key_id="...",
                access_key_secret="..."
            ),
            mount_path="/app/oss",
            sub_path="prefix/path"
        )

    Attributes:
        name: 沙箱内卷的唯一标识符
        host: 主机路径绑定挂载后端
        pvc: 平台管理的命名卷后端（Kubernetes 中的 PVC 或 Docker 中的命名卷）
        ossfs: OSSFS 挂载后端
        mount_path: 容器内挂载卷的绝对路径
        read_only: 如果为 true，卷以只读方式挂载，默认为 false（读写）
        sub_path: 后端路径下要挂载的可选子目录
    """

    name: str = Field(
        ...,
        description="沙箱内卷的唯一标识符",
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
        max_length=63,
    )
    host: Optional[Host] = Field(
        None,
        description="主机路径绑定挂载后端",
    )
    pvc: Optional[PVC] = Field(
        None,
        description="平台管理的命名卷后端（Kubernetes 中的 PVC 或 Docker 中的命名卷）",
    )
    ossfs: Optional[OSSFS] = Field(
        None,
        description="OSSFS 挂载后端",
    )
    mount_path: str = Field(
        ...,
        alias="mountPath",
        description="容器内挂载卷的绝对路径",
        pattern=r"^/.*",
    )
    read_only: bool = Field(
        False,
        alias="readOnly",
        description="如果为 true，卷以只读方式挂载，默认为 false（读写）",
    )
    sub_path: Optional[str] = Field(
        None,
        alias="subPath",
        description="后端路径下要挂载的可选子目录",
    )

    class Config:
        populate_by_name = True

    @model_validator(mode="after")
    def validate_exactly_one_backend(self) -> "Volume":
        """
        验证恰好指定了一个后端类型。

        每个卷必须且只能指定一种后端类型（host、pvc 或 ossfs）。

        Returns:
            self: 验证通过的 Volume 实例

        Raises:
            ValueError: 如果没有指定后端或指定了多个后端
        """
        backends = [self.host, self.pvc, self.ossfs]
        specified = [b for b in backends if b is not None]
        if len(specified) == 0:
            raise ValueError("必须指定恰好一个后端（host、pvc、ossfs），但未提供任何后端。")
        if len(specified) > 1:
            raise ValueError("必须指定恰好一个后端（host、pvc、ossfs），但提供了多个后端。")
        return self


# ============================================================================
# 沙箱状态（Sandbox Status）
# ============================================================================

class SandboxStatus(BaseModel):
    """
    详细的状态信息，包含生命周期状态和转换详情。

    用于描述沙箱当前的生命周期状态，以及导致该状态的原因和相关信息。

    生命周期状态包括：
    - Pending: 沙箱正在创建中
    - Running: 沙箱正在运行
    - Pausing: 沙箱正在暂停中
    - Paused: 沙箱已暂停
    - Stopping: 沙箱正在停止中
    - Terminated: 沙箱已终止
    - Failed: 沙箱创建或运行失败

    Attributes:
        state: 当前生命周期状态（Pending、Running、Pausing、Paused、Stopping、Terminated、Failed）
        reason: 当前状态的简短机器可读原因代码
        message: 描述当前状态或状态转换原因的人类可读消息
        last_transition_at: 最后一次状态转换的时间戳
    """
    state: str = Field(
        ...,
        description="当前生命周期状态（Pending、Running、Pausing、Paused、Stopping、Terminated、Failed）",
    )
    reason: Optional[str] = Field(
        None,
        description="当前状态的简短机器可读原因代码",
    )
    message: Optional[str] = Field(
        None,
        description="描述当前状态或状态转换原因的人类可读消息",
    )
    last_transition_at: Optional[datetime] = Field(
        None,
        alias="lastTransitionAt",
        description="最后一次状态转换的时间戳",
    )

    class Config:
        populate_by_name = True


# ============================================================================
# 沙箱模型（Sandbox Models）
# ============================================================================

class CreateSandboxRequest(BaseModel):
    """
    从容器镜像创建新沙箱的请求。

    包含创建沙箱所需的所有参数，包括镜像、资源限制、环境变量等。

    Examples:
        CreateSandboxRequest(
            image=ImageSpec(uri="python:3.11"),
            resource_limits=ResourceLimits({"cpu": "500m", "memory": "512Mi"}),
            entrypoint=["python", "/app/main.py"],
            timeout=3600,
            env={"PYTHONUNBUFFERED": "1"},
            metadata={"user": "alice", "project": "demo"}
        )

    Attributes:
        image: 沙箱的容器镜像规格
        timeout: 沙箱超时时间（秒），最小值 60。
                 最大值由服务器的 max_sandbox_timeout_seconds 控制。
                 如果省略或为 null，沙箱不会自动终止，需要显式删除。
                 注意：手动清理支持取决于运行时；Kubernetes 提供者在运行时不支持非过期沙箱时可能会拒绝 null timeout。
        resource_limits: 沙箱实例的运行时资源约束
        env: 注入到沙箱运行时的环境变量
        metadata: 用于管理、过滤和标签的自定义键值对元数据
        entrypoint: 作为沙箱入口进程执行的命令
        network_policy: 可选的出站网络策略，形状匹配 egress sidecar 的 /policy 端点，
                        空/省略表示允许所有，直到更新
        volumes: 沙箱的存储挂载，每个卷条目指定一个命名的后端特定存储源和通用挂载设置，
                 每个卷条目必须恰好指定一种后端类型
        extensions: 提供者的不透明容器，用于提供核心 API 未涵盖的特定于提供者或瞬态参数
    """
    image: ImageSpec = Field(..., description="沙箱的容器镜像规格")
    timeout: Optional[int] = Field(
        None,
        ge=60,
        description=(
            "沙箱超时时间（秒），最小值 60。"
            "最大值由服务器的 max_sandbox_timeout_seconds 控制。"
            "如果省略或为 null，沙箱不会自动终止，需要显式删除。"
            "注意：手动清理支持取决于运行时；Kubernetes 提供者在运行时不支持非过期沙箱时可能会拒绝 null timeout。"
        ),
    )
    resource_limits: ResourceLimits = Field(
        ...,
        alias="resourceLimits",
        description="沙箱实例的运行时资源约束",
    )
    env: Optional[Dict[str, Optional[str]]] = Field(
        None,
        description="注入到沙箱运行时的环境变量",
    )
    metadata: Optional[Dict[str, str]] = Field(
        None,
        description="用于管理、过滤和标签的自定义键值对元数据",
    )
    entrypoint: List[str] = Field(
        ...,
        min_length=1,
        description="作为沙箱入口进程执行的命令",
        example=["python", "/app/main.py"],
    )
    network_policy: Optional[NetworkPolicy] = Field(
        None,
        alias="networkPolicy",
        description=(
            "可选的出站网络策略。形状匹配 egress sidecar 的 /policy 端点。"
            "空/省略表示启动时允许所有。"
        ),
    )
    volumes: Optional[List[Volume]] = Field(
        None,
        description=(
            "沙箱的存储挂载。每个卷条目指定一个命名的后端特定存储源和通用挂载设置。"
            "每个卷条目必须恰好指定一种后端类型。"
        ),
    )
    extensions: Optional[Dict[str, str]] = Field(
        None,
        description="提供者的不透明容器，用于提供核心 API 未涵盖的特定于提供者或瞬态参数",
    )

    class Config:
        populate_by_name = True


class CreateSandboxResponse(BaseModel):
    """
    创建新沙箱的响应。

    包含沙箱的基本信息，但不包括镜像和 updatedAt 字段。

    Attributes:
        id: 沙箱唯一标识符
        status: 当前生命周期状态和详细状态信息
        metadata: 创建请求中的自定义元数据
        expires_at: 沙箱自动终止的时间戳，手动清理启用时为 null
        created_at: 沙箱创建时间戳
        entrypoint: 创建请求中的入口进程规格
    """
    id: str = Field(..., description="沙箱唯一标识符")
    status: SandboxStatus = Field(..., description="当前生命周期状态和详细状态信息")
    metadata: Optional[Dict[str, str]] = Field(None, description="创建请求中的自定义元数据")
    expires_at: Optional[datetime] = Field(
        None,
        alias="expiresAt",
        description="沙箱自动终止的时间戳，手动清理启用时为 null",
    )
    created_at: datetime = Field(..., alias="createdAt", description="沙箱创建时间戳")
    entrypoint: List[str] = Field(..., description="创建请求中的入口进程规格")

    class Config:
        populate_by_name = True


class Sandbox(BaseModel):
    """
    从容器镜像配置的运行时执行环境。

    这是沙箱资源的完整表示，包含所有相关信息。

    Attributes:
        id: 沙箱唯一标识符
        image: 用于配置此沙箱的容器镜像规格
        status: 当前生命周期状态和详细状态信息
        metadata: 创建请求中的自定义元数据
        entrypoint: 作为沙箱入口进程执行的命令
        expires_at: 沙箱自动终止的时间戳，手动清理启用时为 null
        created_at: 沙箱创建时间戳
    """
    id: str = Field(..., description="沙箱唯一标识符")
    image: ImageSpec = Field(..., description="用于配置此沙箱的容器镜像规格")
    status: SandboxStatus = Field(..., description="当前生命周期状态和详细状态信息")
    metadata: Optional[Dict[str, str]] = Field(None, description="创建请求中的自定义元数据")
    entrypoint: List[str] = Field(..., description="作为沙箱入口进程执行的命令")
    expires_at: Optional[datetime] = Field(
        None,
        alias="expiresAt",
        description="沙箱自动终止的时间戳，手动清理启用时为 null",
    )
    created_at: datetime = Field(..., alias="createdAt", description="沙箱创建时间戳")

    class Config:
        populate_by_name = True


# ============================================================================
# 列表沙箱（List Sandboxes）
# ============================================================================

class SandboxFilter(BaseModel):
    """
    列出沙箱时的过滤条件。

    用于根据状态或元数据过滤沙箱列表。

    Examples:
        # 按状态过滤
        SandboxFilter(state=["Running", "Paused"])

        # 按元数据过滤
        SandboxFilter(metadata={"user": "alice", "project": "demo"})

        # 组合过滤
        SandboxFilter(
            state=["Running"],
            metadata={"user": "alice"}
        )

    Attributes:
        state: 按生命周期状态过滤（status.state）- 支持 OR 逻辑，
               如 ["Running", "Paused"] 会匹配状态为 Running 或 Paused 的沙箱
        metadata: 按元数据键值对过滤（AND 逻辑），
                  如 {"user": "alice", "project": "demo"} 会匹配同时具有这两个元数据的沙箱
    """
    state: Optional[List[str]] = Field(
        None,
        min_length=1,
        description="按生命周期状态过滤（status.state）- 支持 OR 逻辑",
    )
    metadata: Optional[Dict[str, str]] = Field(
        None,
        description="按元数据键值对过滤（AND 逻辑）",
    )


class PaginationRequest(BaseModel):
    """
    列表请求的分页参数。

    Attributes:
        page: 页码，从 1 开始
        page_size: 每页的项目数，范围 1-200，默认 20
    """
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(
        20,
        ge=1,
        le=200,
        alias="pageSize",
        description="每页的项目数",
    )

    class Config:
        populate_by_name = True


class ListSandboxesRequest(BaseModel):
    """
    复杂列表查询的请求体。

    包含过滤条件和分页参数。

    Examples:
        # 基本列表（无过滤，无分页）
        ListSandboxesRequest()

        # 带过滤和分页
        ListSandboxesRequest(
            filter=SandboxFilter(state=["Running"], metadata={"user": "alice"}),
            pagination=PaginationRequest(page=1, page_size=10)
        )

    Attributes:
        filter: 过滤条件（所有条件使用 AND 逻辑组合）
        pagination: 分页参数，可选
    """
    filter: SandboxFilter = Field(
        default_factory=SandboxFilter,
        description="过滤条件（所有条件使用 AND 逻辑组合）",
    )
    pagination: Optional[PaginationRequest] = Field(None, description="分页参数")


class PaginationInfo(BaseModel):
    """
    列表响应的分页元数据。

    Attributes:
        page: 当前页码
        page_size: 每页的项目数
        total_items: 匹配的总项目数
        total_pages: 总页数
        has_next_page: 当前页之后是否还有更多页
    """
    page: int = Field(..., ge=1, description="当前页码")
    page_size: int = Field(..., ge=1, alias="pageSize", description="每页的项目数")
    total_items: int = Field(..., ge=0, alias="totalItems", description="匹配的总项目数")
    total_pages: int = Field(..., ge=0, alias="totalPages", description="总页数")
    has_next_page: bool = Field(..., alias="hasNextPage", description="当前页之后是否还有更多页")

    class Config:
        populate_by_name = True


class ListSandboxesResponse(BaseModel):
    """
    沙箱的分页集合响应。

    Attributes:
        items: 沙箱列表
        pagination: 分页元数据
    """
    items: List[Sandbox] = Field(..., description="沙箱列表")
    pagination: PaginationInfo = Field(..., description="分页元数据")


# ============================================================================
# 续期过期时间（Renew Expiration）
# ============================================================================

class RenewSandboxExpirationRequest(BaseModel):
    """
    续期沙箱过期时间的请求。

    用于延长沙箱的生命周期，设置新的绝对过期时间。

    Examples:
        RenewSandboxExpirationRequest(
            expires_at=datetime.fromisoformat("2025-12-31T23:59:59Z")
        )

    Attributes:
        expires_at: 新的绝对过期时间，UTC 格式（RFC 3339），必须是未来的时间
    """
    expires_at: datetime = Field(
        ...,
        alias="expiresAt",
        description="新的绝对过期时间，UTC 格式（RFC 3339），必须是未来的时间",
    )

    class Config:
        populate_by_name = True


class RenewSandboxExpirationResponse(BaseModel):
    """
    续期沙箱过期时间的响应。

    Attributes:
        expires_at: 新的绝对过期时间，UTC 格式（RFC 3339）
    """
    expires_at: datetime = Field(
        ...,
        alias="expiresAt",
        description="新的绝对过期时间，UTC 格式（RFC 3339）",
    )

    class Config:
        populate_by_name = True


# ============================================================================
# 端点（Endpoint）
# ============================================================================

class Endpoint(BaseModel):
    """
    用于访问沙箱内运行服务的端点。

    提供访问沙箱内服务的公共端点 URL。

    Examples:
        # 基本端点
        Endpoint(endpoint="192.168.1.100:8080")

        # 带请求头的端点（用于基于请求头的路由）
        Endpoint(
            endpoint="192.168.1.100:8080",
            headers={"X-Route-Id": "sandbox-123"}
        )

    Attributes:
        endpoint: 为沙箱服务暴露的公共端点字符串（host[:port]/path）
        headers: 访问端点时需要的可选请求头（如用于基于请求头的路由）
    """
    endpoint: str = Field(
        ...,
        description="为沙箱服务暴露的公共端点字符串（host[:port]/path）",
    )
    headers: Optional[dict[str, str]] = Field(
        default=None,
        description="访问端点时需要的可选请求头（如用于基于请求头的路由）",
    )


# ============================================================================
# 错误响应（Error Response）
# ============================================================================

class ErrorResponse(BaseModel):
    """
    所有非 2xx HTTP 响应的标准错误响应格式。

    HTTP 状态码表示错误类别；code 和 message 提供详细信息。

    Examples:
        # 资源未找到
        ErrorResponse(
            code="NOT_FOUND",
            message="Sandbox '123' not found"
        )

        # 无效请求
        ErrorResponse(
            code="INVALID_REQUEST",
            message="Missing required field 'image'"
        )

        # 内部服务器错误
        ErrorResponse(
            code="INTERNAL_ERROR",
            message="Failed to connect to Docker daemon"
        )

    Attributes:
        code: 机器可读的错误代码（如 INVALID_REQUEST、NOT_FOUND、INTERNAL_ERROR）
        message: 人类可读的错误消息，描述问题及如何修复
    """
    code: str = Field(
        ...,
        description="机器可读的错误代码（如 INVALID_REQUEST、NOT_FOUND、INTERNAL_ERROR）",
    )
    message: str = Field(
        ...,
        description="人类可读的错误消息，描述问题及如何修复",
    )
