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
沙箱服务层业务逻辑抽象接口。

本模块定义了沙箱服务的抽象基类，所有沙箱服务实现都必须继承此类。
服务层负责：
1. 沙箱生命周期管理：创建、删除、暂停、恢复
2. 沙箱状态查询：获取沙箱信息、列表沙箱
3. 沙箱过期管理：续期过期时间
4. 端点解析：获取沙箱访问端点

设计模式：
- 使用抽象基类 (ABC) 定义接口
- 具体实现（如 DockerSandboxService、KubernetesSandboxService）继承此抽象类
- 工厂函数 (factory.py) 根据配置返回相应的实现实例

沙箱 ID 生成：
- 使用 UUID4 生成唯一标识符
- 格式为标准 UUID 字符串（带连字符）

端口验证：
- 有效端口范围：1-65535
- 使用 socket 模块验证端口可用性

IP 地址解析：
- 用于确定绑定到 0.0.0.0 时的实际 IP
- 优先使用向外连接获取的 IP
- 回退到主机名解析
- 最后回退到本地回环地址
"""

from abc import ABC, abstractmethod
import socket
from uuid import uuid4

from src.api.schema import (
    CreateSandboxRequest,
    CreateSandboxResponse,
    Endpoint,
    ListSandboxesRequest,
    ListSandboxesResponse,
    RenewSandboxExpirationRequest,
    RenewSandboxExpirationResponse,
    Sandbox,
)
from src.services.validators import ensure_valid_port


class SandboxService(ABC):
    """
    沙箱生命周期操作的抽象服务接口。

    此类定义了所有沙箱服务实现的接口。
    实现类应处理沙箱的创建、管理和销毁。

    设计目的：
    1. 定义统一的接口，使不同运行时（Docker、Kubernetes）的实现可以互换
    2. 提供通用的工具方法（如 ID 生成、端口验证、IP 解析）
    3. 强制实现类实现所有必需的方法

    使用示例：
        # 通过工厂函数创建服务实例
        service = create_sandbox_service()

        # 创建沙箱
        response = service.create_sandbox(request)

        # 查询沙箱
        sandbox = service.get_sandbox(sandbox_id)

        # 删除沙箱
        service.delete_sandbox(sandbox_id)
    """

    @staticmethod
    def generate_sandbox_id() -> str:
        """
        生成唯一的沙箱标识符。

        使用 UUID4 算法生成随机 UUID，符合 RFC4122 标准。
        UUID4 提供足够的随机性，几乎不会发生冲突。

        Returns:
            str: RFC4122 兼容的 UUID4 字符串（带连字符）
                  格式示例：'550e8400-e29b-41d4-a716-446655440000'

        Examples:
            >>> SandboxService.generate_sandbox_id()
            '550e8400-e29b-41d4-a716-446655440000'
        """
        return str(uuid4())

    @staticmethod
    def _resolve_bind_ip(family: int = socket.AF_INET) -> str:
        """
        解析绑定到 0.0.0.0 时的对外 IP 地址。

        当服务器绑定到 0.0.0.0 时，需要确定实际的对外 IP 地址用于返回端点。
        此方法通过尝试连接到外部地址来获取本地 IP。

        解析策略（按优先级）：
        1. 通过连接到外部地址（如 8.8.8.8）获取源 IP
        2. 通过主机名解析获取 IP
        3. 回退到本地回环地址（127.0.0.1 或 ::1）

        Args:
            family: 地址族，socket.AF_INET（IPv4）或 socket.AF_INET6（IPv6）

        Returns:
            str: 检测到的本地 IP 地址，或安全的回退地址 127.0.0.1（IPv4）/::1（IPv6）

        Examples:
            >>> SandboxService._resolve_bind_ip(socket.AF_INET)
            '192.168.1.100'
            >>> SandboxService._resolve_bind_ip(socket.AF_INET6)
            'fe80::1'
        """
        try:
            # 尝试连接到外部地址以确定源 IP
            # 对于 IPv6，使用 Google 的公共 DNS 2001:4860:4860::8888
            # 对于 IPv4，使用 Google 的公共 DNS 8.8.8.8
            target = ("2001:4860:4860::8888", 80, 0, 0) if family == socket.AF_INET6 else ("8.8.8.8", 80)
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                # connect() 不会实际发送数据包，只是设置默认路由
                sock.connect(target)
                # getsockname() 返回用于连接的本地地址
                ip = sock.getsockname()[0]
                if ip:
                    # 对于 IPv6，跳过链路本地地址（fe80 开头）
                    if family == socket.AF_INET or not ip.startswith("fe80"):
                        return ip
        except OSError:
            # 如果 IPv6 失败，尝试 IPv4
            if family == socket.AF_INET6:
                return SandboxService._resolve_bind_ip(socket.AF_INET)

        # 方法 1 失败，尝试通过主机名解析
        try:
            family_name = socket.AF_INET6 if family == socket.AF_INET6 else socket.AF_INET
            hostname = socket.gethostname()
            # 获取主机名的所有地址信息
            infos = socket.getaddrinfo(hostname, None, family_name, socket.SOCK_DGRAM)
            if infos:
                # 返回第一个地址
                addr = infos[0][4][0]
                if addr:
                    return addr
        except OSError:
            pass

        # 所有方法都失败，返回本地回环地址
        return "::1" if family == socket.AF_INET6 else "127.0.0.1"

    @staticmethod
    def validate_port(port: int) -> None:
        """
        验证提供的端口是否在允许的范围内。

        使用验证器函数确保端口号有效。
        有效端口范围：1-65535

        Args:
            port: 要验证的端口号

        Raises:
            ValueError: 如果端口不在 1-65535 范围内

        Examples:
            >>> SandboxService.validate_port(8080)  # 正常返回
            >>> SandboxService.validate_port(0)     # 抛出 ValueError
            >>> SandboxService.validate_port(70000) # 抛出 ValueError
        """
        ensure_valid_port(port)

    @abstractmethod
    def create_sandbox(self, request: CreateSandboxRequest) -> CreateSandboxResponse:
        """
        从容器镜像创建新的沙箱。

        这是创建沙箱的主要入口点。实现类应：
        1. 验证请求参数
        2. 生成沙箱 ID
        3. 拉取容器镜像（如果需要）
        4. 创建和配置容器/工作负载
        5. 启动容器/工作负载
        6. 设置过期定时器（如果指定了超时）
        7. 返回沙箱信息

        Args:
            request: 沙箱创建请求，包含镜像、资源限制、入口点等

        Returns:
            CreateSandboxResponse: 创建的沙箱信息

        Raises:
            HTTPException: 如果沙箱创建失败（如镜像拉取失败、资源不足等）
        """
        pass

    @abstractmethod
    def list_sandboxes(self, request: ListSandboxesRequest) -> ListSandboxesResponse:
        """
        列出沙箱，支持可选的过滤和分页。

        实现类应：
        1. 根据过滤条件查询沙箱
        2. 应用分页逻辑
        3. 返回沙箱列表和分页元数据

        过滤条件：
        - state: 按生命周期状态过滤，支持 OR 逻辑
        - metadata: 按元数据键值对过滤，支持 AND 逻辑

        Args:
            request: 列表请求，包含过滤器和分页参数

        Returns:
            ListSandboxesResponse: 沙箱的分页列表
        """
        pass

    @abstractmethod
    def get_sandbox(self, sandbox_id: str) -> Sandbox:
        """
        根据 ID 获取沙箱。

        实现类应：
        1. 查找沙箱容器/工作负载
        2. 解析状态信息
        3. 返回完整的沙箱对象

        Args:
            sandbox_id: 沙箱唯一标识符

        Returns:
            Sandbox: 完整的沙箱信息

        Raises:
            HTTPException: 如果沙箱未找到（404 Not Found）
        """
        pass

    @abstractmethod
    def delete_sandbox(self, sandbox_id: str) -> None:
        """
        删除沙箱。

        实现类应：
        1. 查找沙箱容器/工作负载
        2. 停止容器/工作负载（如果正在运行）
        3. 删除容器/工作负载
        4. 清理相关资源（如挂载点、sidecar 等）
        5. 取消过期定时器

        Args:
            sandbox_id: 沙箱唯一标识符

        Raises:
            HTTPException: 如果沙箱未找到或删除失败
        """
        pass

    @abstractmethod
    def pause_sandbox(self, sandbox_id: str) -> None:
        """
        暂停运行中的沙箱。

        实现类应：
        1. 查找沙箱容器/工作负载
        2. 验证容器处于 Running 状态
        3. 暂停容器/工作负载
        4. 更新状态为 Paused

        Args:
            sandbox_id: 沙箱唯一标识符

        Raises:
            HTTPException: 如果沙箱未找到或无法暂停（如状态不允许）
        """
        pass

    @abstractmethod
    def resume_sandbox(self, sandbox_id: str) -> None:
        """
        恢复已暂停的沙箱。

        实现类应：
        1. 查找沙箱容器/工作负载
        2. 验证容器处于 Paused 状态
        3. 恢复容器/工作负载
        4. 更新状态为 Running

        Args:
            sandbox_id: 沙箱唯一标识符

        Raises:
            HTTPException: 如果沙箱未找到或无法恢复（如状态不允许）
        """
        pass

    @abstractmethod
    def renew_expiration(
        self,
        sandbox_id: str,
        request: RenewSandboxExpirationRequest,
    ) -> RenewSandboxExpirationResponse:
        """
        续期沙箱过期时间。

        实现类应：
        1. 查找沙箱容器/工作负载
        2. 验证新的过期时间有效（将来时间，晚于当前过期时间）
        3. 更新容器/工作负载的过期时间标签
        4. 取消旧的过期定时器，设置新的定时器
        5. 返回新的过期时间

        Args:
            sandbox_id: 沙箱唯一标识符
            request: 续期请求，包含新的过期时间

        Returns:
            RenewSandboxExpirationResponse: 更新后的过期时间

        Raises:
            HTTPException: 如果沙箱未找到或续期失败（如过期时间无效）
        """
        pass

    @abstractmethod
    def get_endpoint(self, sandbox_id: str, port: int, resolve_internal: bool = False) -> Endpoint:
        """
        获取沙箱访问端点。

        实现类应：
        1. 查找沙箱容器/工作负载
        2. 解析端点信息（IP 和端口）
        3. 返回端点对象

        端点解析模式：
        - resolve_internal=False（默认）：返回外部访问端点，考虑路由器配置
        - resolve_internal=True：返回内部容器 IP，用于服务器代理，忽略路由器配置

        Args:
            sandbox_id: 沙箱唯一标识符
            port: 沙箱内服务监听的端口号
            resolve_internal: 如果为 True，返回内部容器 IP（用于代理），忽略路由器配置

        Returns:
            Endpoint: 公共端点 URL，可能包含请求头

        Raises:
            HTTPException: 如果沙箱未找到或端点不可用
        """
        pass
