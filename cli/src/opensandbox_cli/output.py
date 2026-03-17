# Copyright 2026 Alibaba Group Holding Ltd.
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

"""输出格式化工具模块。

本模块定义了 OutputFormatter 类，用于将数据以不同格式输出：
1. table: 表格格式（使用 rich 库渲染）
2. json: JSON 格式
3. yaml: YAML 格式

主要功能：
- print_model: 打印单个 Pydantic 模型
- print_models: 打印多个 Pydantic 模型列表
- print_dict: 打印字典
- print_text: 打印原始文本

使用示例：
    formatter = OutputFormatter("table", color=True)
    formatter.print_dict({"key": "value"}, title="Info")
    formatter.print_models(items, columns=["id", "name"])
"""

from __future__ import annotations

import json
import sys
from typing import Any, Sequence

import click

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table


class OutputFormatter:
    """输出格式化工具类。

    支持三种输出格式：
    - table: 表格格式，适合终端显示
    - json: JSON 格式，适合机器处理
    - yaml: YAML 格式，适合人工阅读配置

    属性：
        fmt: 输出格式（table/json/yaml）
        console: rich 控制台实例

    使用示例：
        # JSON 输出
        fmt = OutputFormatter("json")
        fmt.print_dict({"key": "value"})

        # 表格输出
        fmt = OutputFormatter("table", color=True)
        fmt.print_models(items, columns=["id", "name", "status"])
    """

    def __init__(self, fmt: str = "table", *, color: bool = True) -> None:
        """初始化输出格式化工具。

        参数：
            fmt: 输出格式（table/json/yaml），默认为 table
            color: 是否启用彩色输出，默认为 True
        """
        self.fmt = fmt
        self.console = Console(
            stderr=False, no_color=not color, force_terminal=None
        )

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def print_model(self, model: BaseModel, title: str | None = None) -> None:
        """打印单个 Pydantic 模型。

        根据当前格式设置，以 key-value 表格、JSON 或 YAML 格式输出模型数据。

        参数：
            model: 要打印的 Pydantic 模型
            title: 可选的标题

        使用示例：
            formatter.print_model(sandbox_info, title="Sandbox Info")
        """
        data = _model_to_dict(model)
        if self.fmt == "json":
            self._print_json(data)
        elif self.fmt == "yaml":
            self._print_yaml(data)
        else:
            self._print_kv_table(data, title=title)

    def print_models(
        self,
        models: Sequence[BaseModel],
        columns: list[str],
        *,
        title: str | None = None,
    ) -> None:
        """打印多个 Pydantic 模型列表。

        根据当前格式设置，以表格、JSON 数组或 YAML 数组格式输出模型列表。

        参数：
            models: 要打印的 Pydantic 模型列表
            columns: 要显示的列名列表
            title: 可选的标题

        使用示例：
            formatter.print_models(
                sandboxes,
                columns=["id", "status", "image"],
                title="Sandboxes"
            )
        """
        rows = [_model_to_dict(m) for m in models]
        if self.fmt == "json":
            self._print_json(rows)
        elif self.fmt == "yaml":
            self._print_yaml(rows)
        else:
            self._print_table(rows, columns, title=title)

    def print_dict(self, data: dict[str, Any], title: str | None = None) -> None:
        """打印字典数据。

        根据当前格式设置输出字典数据。

        参数：
            data: 要打印的字典
            title: 可选的标题

        使用示例：
            formatter.print_dict({"status": "ok", "count": 10})
        """
        if self.fmt == "json":
            self._print_json(data)
        elif self.fmt == "yaml":
            self._print_yaml(data)
        else:
            self._print_kv_table(data, title=title)

    def print_text(self, text: str) -> None:
        """打印原始文本。

        忽略格式设置，直接输出原始文本内容。

        参数：
            text: 要打印的文本
        """
        click.echo(text)

    # ------------------------------------------------------------------
    # 内部方法：具体渲染实现
    # ------------------------------------------------------------------

    def _print_json(self, data: Any) -> None:
        """以 JSON 格式输出数据。

        参数：
            data: 要输出的数据（将被 JSON 序列化）
        """
        click.echo(json.dumps(data, indent=2, default=str))

    def _print_yaml(self, data: Any) -> None:
        """以 YAML 格式输出数据。

        参数：
            data: 要输出的数据（将被 YAML 序列化）

        异常：
            如果 PyYAML 未安装，输出错误信息并退出
        """
        if yaml is None:
            click.secho(
                "PyYAML is not installed. Use --output json instead.", fg="red", err=True
            )
            sys.exit(1)
        click.echo(yaml.dump(data, default_flow_style=False, allow_unicode=True).rstrip())

    def _print_kv_table(self, data: dict[str, Any], *, title: str | None = None) -> None:
        """以 key-value 表格格式输出数据。

        参数：
            data: 要输出的字典数据
            title: 表格标题
        """
        table = Table(title=title, show_header=True, header_style="bold")
        table.add_column("Key", style="cyan")
        table.add_column("Value")
        for k, v in data.items():
            table.add_row(str(k), str(v) if v is not None else "-")
        self.console.print(table)

    def _print_table(
        self,
        rows: list[dict[str, Any]],
        columns: list[str],
        *,
        title: str | None = None,
    ) -> None:
        """以表格格式输出多行数据。

        参数：
            rows: 行数据列表，每项为一个字典
            columns: 列名列表
            title: 表格标题
        """
        table = Table(title=title, show_header=True, header_style="bold")
        for col in columns:
            table.add_column(col.upper())
        for row in rows:
            table.add_row(*(str(row.get(col, "-")) for col in columns))
        self.console.print(table)


# ------------------------------------------------------------------
# 辅助函数
# ------------------------------------------------------------------


def _model_to_dict(model: BaseModel) -> dict[str, Any]:
    """将 Pydantic 模型转换为字典。

    参数：
        model: Pydantic 模型实例

    返回：
        dict[str, Any]: 模型的字典表示
    """
    return model.model_dump(mode="json")
