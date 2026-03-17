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
Agent-sandbox 模板加载器和合并器模块。

本模块提供了 AgentSandboxTemplateManager 类，用于：
- 加载 Agent-sandbox CRD 的 YAML 模板文件
- 将运行时生成的 manifest 与模板合并

Agent-sandbox 是 Kubernetes 上的一个 CRD（自定义资源定义），
用于管理 Agent 沙箱环境。模板允许用户自定义沙箱的配置，
如 Pod 模板、资源限制等。

使用示例：
    >>> manager = AgentSandboxTemplateManager("/path/to/template.yaml")
    >>> runtime_manifest = {"apiVersion": "...", "kind": "...", ...}
    >>> merged = manager.merge_with_runtime_values(runtime_manifest)
"""

from typing import Optional

from src.services.k8s.template_manager import BaseSandboxTemplateManager


class AgentSandboxTemplateManager(BaseSandboxTemplateManager):
    """
    Agent-sandbox Sandbox CR 模板管理器。

    继承自 BaseSandboxTemplateManager，专门用于处理 Agent-sandbox 类型的模板。

    功能：
    - 加载 Agent-sandbox 模板 YAML 文件
    - 将运行时生成的 manifest 与模板深度合并
    - 支持模板字段覆盖和扩展

    Attributes:
        template_file_path: 模板文件路径（可选）
        _template_kind: 模板类型标识（"Agent-sandbox"）

    Examples:
        >>> # 使用模板文件初始化
        >>> manager = AgentSandboxTemplateManager("/etc/opensandbox/agent-template.yaml")
        >>> # 不使用模板（使用默认配置）
        >>> manager = AgentSandboxTemplateManager()
    """

    def __init__(self, template_file_path: Optional[str] = None):
        """
        初始化 Agent-sandbox 模板管理器。

        Args:
            template_file_path: 模板文件路径（可选）
                               如果为 None，则不使用模板，直接使用运行时配置

        Raises:
            FileNotFoundError: 如果指定的模板文件不存在
            ValueError: 如果模板文件格式无效
            RuntimeError: 如果加载模板时发生其他错误
        """
        super().__init__(template_file_path, template_kind="Agent-sandbox")
