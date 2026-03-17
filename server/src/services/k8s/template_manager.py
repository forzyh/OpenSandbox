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
Kubernetes Sandbox CR Manifest 的共享模板加载器和合并器模块。

本模块提供了 BaseSandboxTemplateManager 类，用于：
- 加载 YAML 格式的 Sandbox 模板文件
- 将运行时生成的 manifest 与模板进行深度合并

模板功能允许用户自定义 Sandbox CR 的配置，如：
- Pod 模板spec（容器、卷、资源限制等）
- 元数据（标签、注释等）
- 其他 CR 特定字段

使用示例：
    >>> manager = BaseSandboxTemplateManager("/path/to/template.yaml", "BatchSandbox")
    >>> runtime_manifest = {"apiVersion": "...", "kind": "...", "spec": {...}}
    >>> merged = manager.merge_with_runtime_values(runtime_manifest)
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


class BaseSandboxTemplateManager:
    """
    用于加载 YAML 模板和合并运行时 manifest 的共享管理器。

    该类实现了模板加载和深度合并的核心逻辑，可以被不同类型的
    Sandbox 模板管理器继承使用。

    合并规则：
    - 运行时 manifest 的字段优先于模板
    - 字典类型字段进行深度合并
    - 列表类型字段直接用运行时值覆盖
    - None 值被忽略

    Attributes:
        template_file_path: 模板文件路径
        _template_kind: 模板类型标识（如 "BatchSandbox"、"Agent-sandbox"）
        _template: 加载的模板内容（字典）

    Examples:
        >>> manager = BaseSandboxTemplateManager("/etc/template.yaml", "BatchSandbox")
        >>> template = manager.get_base_template()
        >>> merged = manager.merge_with_runtime_values(runtime_manifest)
    """

    def __init__(self, template_file_path: Optional[str], template_kind: str):
        """
        初始化模板管理器。

        Args:
            template_file_path: 模板文件路径（可选）
                               如果为 None，则不使用模板
            template_kind: 模板类型标识（用于错误消息）

        Raises:
            FileNotFoundError: 如果指定的模板文件不存在
            ValueError: 如果模板文件格式无效（不是 YAML 对象）
            RuntimeError: 如果加载模板时发生其他错误
        """
        self.template_file_path = template_file_path
        self._template_kind = template_kind
        self._template: Optional[Dict[str, Any]] = None

        if template_file_path:
            self._load_template()

    def _load_template(self) -> None:
        """
        从文件加载 YAML 模板。

        加载逻辑：
        1. 检查文件是否存在
        2. 读取并解析 YAML 内容
        3. 验证解析结果是字典类型

        Raises:
            FileNotFoundError: 如果模板文件不存在
            ValueError: 如果模板文件格式无效
            RuntimeError: 如果加载过程中发生其他错误
        """
        if not self.template_file_path:
            return

        template_path = Path(self.template_file_path).expanduser()

        if not template_path.exists():
            raise FileNotFoundError(
                f"{self._template_kind} 模板文件不存在：{template_path}"
            )

        try:
            with template_path.open("r") as f:
                self._template = yaml.safe_load(f)

            if not isinstance(self._template, dict):
                raise ValueError(
                    f"无效的模板文件 {template_path}：必须是 YAML 对象，"
                    f"但得到了 {type(self._template).__name__}"
                )

            logger.info("已从 %s 加载 %s 模板", self._template_kind, template_path)
        except (FileNotFoundError, ValueError):
            raise
        except Exception as e:
            raise RuntimeError(
                f"从 {template_path} 加载 {self._template_kind} 模板失败：{e}"
            ) from e

    def get_base_template(self) -> Dict[str, Any]:
        """
        获取基础模板的深拷贝。

        Returns:
            Dict[str, Any]: 模板字典的深拷贝
                           如果未加载模板，返回空字典

        注意：返回的是深拷贝，调用者可以安全修改而不影响原始模板。
        """
        if self._template:
            return self._deep_copy(self._template)
        return {}

    def merge_with_runtime_values(self, runtime_manifest: Dict[str, Any]) -> Dict[str, Any]:
        """
        将运行时 manifest 与基础模板合并。

        合并规则：
        - 以模板为基础
        - 运行时 manifest 的字段覆盖模板中的对应字段
        - 字典类型字段进行深度合并
        - None 值被忽略

        Args:
            runtime_manifest: 运行时生成的 manifest

        Returns:
            Dict[str, Any]: 合并后的完整 manifest
        """
        base = self.get_base_template()

        if not base:
            # 没有模板，直接返回运行时 manifest
            return runtime_manifest

        return self._deep_merge(base, runtime_manifest)

    @staticmethod
    def _deep_copy(obj: Any) -> Any:
        """
        递归深拷贝对象。

        Args:
            obj: 要拷贝的对象

        Returns:
            Any: 对象的深拷贝

        处理逻辑：
        - 字典：递归拷贝每个键值对
        - 列表：递归拷贝每个元素
        - 其他：直接返回（不可变类型）
        """
        if isinstance(obj, dict):
            return {k: BaseSandboxTemplateManager._deep_copy(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [BaseSandboxTemplateManager._deep_copy(item) for item in obj]
        return obj

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """
        深度合并两个字典。

        合并规则：
        - 以 base 为基础
        - override 中的字段覆盖 base 中的对应字段
        - 如果两个值都是字典，递归合并
        - None 值被忽略

        Args:
            base: 基础字典
            override: 覆盖字典

        Returns:
            Dict[str, Any]: 合并后的字典
        """
        result = base.copy()

        for key, override_value in override.items():
            if override_value is None:
                # 忽略 None 值
                continue

            if key not in result:
                # 新字段，直接添加深拷贝
                result[key] = BaseSandboxTemplateManager._deep_copy(override_value)
            elif isinstance(result[key], dict) and isinstance(override_value, dict):
                # 都是字典，递归合并
                result[key] = BaseSandboxTemplateManager._deep_merge(
                    result[key], override_value
                )
            else:
                # 其他类型，用覆盖值替换
                result[key] = BaseSandboxTemplateManager._deep_copy(override_value)

        return result
