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

"""配置管理命令的实现模块。

本模块实现了 CLI 配置管理的相关命令，包括：
1. config init: 创建默认配置文件
2. config show: 显示当前解析后的配置
3. config set: 设置配置项的值

配置文件格式为 TOML，默认位置为 ~/.opensandbox/config.toml。
配置优先级（从高到低）：
1. CLI 命令行参数
2. 环境变量
3. 配置文件
4. SDK 默认值
"""

from __future__ import annotations

from pathlib import Path

import click

from opensandbox_cli.client import ClientContext
from opensandbox_cli.config import DEFAULT_CONFIG_PATH, init_config_file
from opensandbox_cli.utils import handle_errors


@click.group("config", invoke_without_command=True)
@click.pass_context
def config_group(ctx: click.Context) -> None:
    """配置管理命令组入口。

    当没有指定子命令时，显示帮助信息。

    使用示例：
        osb config --help        # 查看帮助
        osb config init          # 创建配置文件
        osb config show          # 显示当前配置
        osb config set key value # 设置配置项
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ---- init -----------------------------------------------------------------

@click.command("init")
@click.option("--force", is_flag=True, default=False, help="覆盖已存在的配置文件。")
@click.option("--path", "config_path", type=click.Path(path_type=Path), default=None, help="配置文件路径。")
@handle_errors
def config_init(force: bool, config_path: Path | None) -> None:
    """创建默认配置文件。

    在指定路径或默认位置 (~/.opensandbox/config.toml) 创建配置文件模板。

    参数：
        force: 是否强制覆盖已存在的文件
        config_path: 自定义配置文件路径（可选）

    使用示例：
        # 创建默认位置的配置文件
        osb config init

        # 创建到指定路径
        osb config init --path ./my-config.toml

        # 强制覆盖已存在的文件
        osb config init --force
    """
    try:
        path = init_config_file(config_path, force=force)
        click.echo(f"Config file created: {path}")
    except FileExistsError as exc:
        click.secho(str(exc), fg="yellow", err=True)


# ---- show -----------------------------------------------------------------

@click.command("show")
@click.pass_obj
@handle_errors
def config_show(obj: ClientContext) -> None:
    """显示当前解析后的配置。

    显示合并所有配置源（CLI 参数、环境变量、配置文件、默认值）后的最终配置。

    使用示例：
        osb config show
    """
    obj.output.print_dict(obj.resolved_config, title="Resolved Configuration")


# ---- set ------------------------------------------------------------------

@click.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--path", "config_path", type=click.Path(path_type=Path), default=None, help="配置文件路径。")
@handle_errors
def config_set(key: str, value: str, config_path: Path | None) -> None:
    """设置配置项的值。

    支持设置嵌套的 TOML 配置项，key 使用点号分隔（如 connection.domain）。
    自动推断值的类型：布尔值 > 整数 > 浮点数 > 字符串。

    参数：
        key: 配置项键名，格式为 section.field（如 connection.domain）
        value: 配置项值
        config_path: 配置文件路径（可选，默认为 ~/.opensandbox/config.toml）

    使用示例：
        # 设置 API 服务器地址
        osb config set connection.domain localhost:9090

        # 设置 API 密钥
        osb config set connection.api_key my-secret-key

        # 设置输出格式
        osb config set output.format json

        # 设置默认超时
        osb config set defaults.timeout 10m
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        click.secho(f"Config file not found: {path}. Run 'osb config init' first.", fg="red", err=True)
        return

    content = path.read_text()

    # 解析点号分隔的 key（如 connection.domain）
    parts = key.split(".", 1)
    if len(parts) == 2:
        section, field = parts
        import re

        # 匹配 TOML 中的 section 块
        section_pattern = rf"(\[{re.escape(section)}\].*?)(?=\n\[|\Z)"
        section_match = re.search(section_pattern, content, re.DOTALL)

        # 推断 TOML 值类型：布尔值 > 整数 > 浮点数 > 字符串
        def _toml_value(raw: str) -> str:
            if raw.lower() in ("true", "false"):
                return raw.lower()
            try:
                int(raw)
                return raw
            except ValueError:
                pass
            try:
                float(raw)
                return raw
            except ValueError:
                pass
            return f'"{raw}"'

        toml_val = _toml_value(value)

        if section_match:
            # section 已存在，尝试更新或添加字段
            section_text = section_match.group(1)
            field_pattern = rf'^(#?\s*{re.escape(field)}\s*=\s*).*$'
            field_match = re.search(field_pattern, section_text, re.MULTILINE)
            if field_match:
                # 更新已存在的字段
                new_line = f'{field} = {toml_val}'
                new_section = section_text[:field_match.start()] + new_line + section_text[field_match.end():]
                content = content[:section_match.start()] + new_section + content[section_match.end():]
            else:
                # 添加新字段到 section
                insert_pos = section_match.end()
                content = content[:insert_pos] + f'\n{field} = {toml_val}' + content[insert_pos:]
        else:
            # 创建新 section
            content += f'\n[{section}]\n{field} = {toml_val}\n'
    else:
        click.secho("Key must be in 'section.field' format (e.g. connection.domain).", fg="red", err=True)
        return

    path.write_text(content)
    click.echo(f"Set {key} = {value}")
