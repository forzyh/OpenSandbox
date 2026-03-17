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
Kubernetes imagePullSecrets 创建辅助函数模块。

本模块提供了用于创建 Kubernetes imagePullSecrets 的工具函数，
用于私有镜像仓库的身份验证。

imagePullSecrets 是 Kubernetes 中用于拉取私有镜像的机制：
1. 创建包含镜像仓库凭证的 Secret（kubernetes.io/dockerconfigjson 类型）
2. 在 Pod spec 中引用该 Secret
3. Kubernetes 使用凭证从私有仓库拉取镜像

本模块的功能：
- 从 sandbox_id 生成确定的 Secret 名称
- 构建包含镜像仓库凭证的 V1Secret 对象
- 自动设置 ownerReference，使 Secret 随所有者一起被垃圾回收

使用示例：
    >>> secret_name = build_image_pull_secret_name("sandbox-123")
    >>> secret = build_image_pull_secret(
    ...     sandbox_id="sandbox-123",
    ...     image_uri="registry.example.com/my-image:latest",
    ...     auth=ImageAuth(username="user", password="pass"),
    ...     owner_uid="abc-123",
    ...     owner_api_version="sandbox.opensandbox.io/v1alpha1",
    ...     owner_kind="BatchSandbox"
    ... )
    >>> k8s_client.create_secret(namespace="default", body=secret)
"""

import base64
import json

from kubernetes.client import V1ObjectMeta, V1OwnerReference, V1Secret

from src.api.schema import ImageAuth

# imagePullSecret 名称前缀
IMAGE_AUTH_SECRET_PREFIX = "opensandbox-image-auth"


def build_image_pull_secret_name(sandbox_id: str) -> str:
    """
    从 sandbox_id 派生确定的 imagePullSecret 名称。

    使用确定的名称可以：
    - 在创建 Secret 之前就知道名称，便于在 Pod spec 中引用
    - 避免重复创建相同名称的 Secret

    Args:
        sandbox_id: Sandbox 唯一标识符

    Returns:
        str: imagePullSecret 名称，格式为 "opensandbox-image-auth-{sandbox_id}"

    Examples:
        >>> build_image_pull_secret_name("sandbox-123")
        'opensandbox-image-auth-sandbox-123'
    """
    return f"{IMAGE_AUTH_SECRET_PREFIX}-{sandbox_id}"


def build_image_pull_secret(
    sandbox_id: str,
    image_uri: str,
    auth: ImageAuth,
    owner_uid: str,
    owner_api_version: str,
    owner_kind: str,
) -> V1Secret:
    """
    构建用于镜像拉取认证的 kubernetes.io/dockerconfigjson Secret。

    该 Secret 的 ownerReference 指向拥有的 CR，这样当所有者被删除时
    Secret 会自动被垃圾回收。

    Args:
        sandbox_id: Sandbox 标识符（用于派生 Secret 名称）
        image_uri: 容器镜像 URI（用于确定仓库主机名）
        auth: ImageAuth 凭证对象
        owner_uid: 拥有者的 UID
        owner_api_version: 拥有者的 apiVersion（如 "sandbox.opensandbox.io/v1alpha1"）
        owner_kind: 拥有者的 Kind（如 "BatchSandbox"）

    Returns:
        V1Secret: 准备好通过 CoreV1Api 创建的 Secret 对象

    镜像仓库解析规则：
        - 如果镜像 URI 包含域名（如 "registry.example.com/ns/image:tag"），提取域名
        - 否则使用 Docker Hub 默认地址（"https://index.docker.io/v1/"）

    Docker config JSON 格式：
        {
            "auths": {
                "<registry>": {
                    "username": "<username>",
                    "password": "<password>",
                    "auth": "<base64(username:password)>"
                }
            }
        }

    Examples:
        >>> secret = build_image_pull_secret(
        ...     sandbox_id="sandbox-123",
        ...     image_uri="registry.example.com/my-image:latest",
        ...     auth=ImageAuth(username="user", password="pass"),
        ...     owner_uid="abc-123",
        ...     owner_api_version="sandbox.opensandbox.io/v1alpha1",
        ...     owner_kind="BatchSandbox"
        ... )
    """
    secret_name = build_image_pull_secret_name(sandbox_id)

    # 从镜像 URI 派生仓库主机名
    # 例如："registry.example.com/ns/image:tag" -> "registry.example.com"
    # 例如："python:3.11" -> "https://index.docker.io/v1/"
    parts = image_uri.split("/")
    if len(parts) >= 2 and ("." in parts[0] or ":" in parts[0]):
        # 第一部分看起来像域名
        registry = parts[0]
    else:
        # 使用 Docker Hub 默认地址
        registry = "https://index.docker.io/v1/"

    # 构建认证字符串（base64 编码的 username:password）
    auth_str = base64.b64encode(
        f"{auth.username}:{auth.password}".encode()
    ).decode()

    # 构建 docker config JSON
    docker_config = {
        "auths": {
            registry: {
                "username": auth.username,
                "password": auth.password,
                "auth": auth_str,
            }
        }
    }
    # base64 编码 docker config
    docker_config_b64 = base64.b64encode(
        json.dumps(docker_config).encode()
    ).decode()

    # 构建 V1Secret 对象
    return V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=V1ObjectMeta(
            name=secret_name,
            owner_references=[
                V1OwnerReference(
                    api_version=owner_api_version,
                    kind=owner_kind,
                    name=sandbox_id,
                    uid=owner_uid,
                    controller=False,
                )
            ],
        ),
        type="kubernetes.io/dockerconfigjson",
        data={".dockerconfigjson": docker_config_b64},
    )
