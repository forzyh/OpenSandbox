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

"""CLI 主入口模块。

本模块定义了 OpenSandbox CLI 的根命令组和全局选项，并注册所有子命令组。

全局选项包括：
- --api-key: API 认证密钥
- --domain: API 服务器域名
- --protocol: 通信协议（http/https）
- --timeout: 请求超时（秒）
- -o/--output: 输出格式（table/json/yaml）
- --config: 配置文件路径
- -v/--verbose: 启用调试输出
- --no-color: 禁用彩色输出

注册的子命令组：
- sandbox: 沙盒生命周期管理
- command: 命令执行
- exec: 命令执行快捷方式
- file: 文件操作
- code: 代码执行
- config: 配置管理
"""

from __future__ import annotations

from pathlib import Path

import click

from opensandbox_cli import __version__
from opensandbox_cli.client import ClientContext
from opensandbox_cli.commands.code import code_group
from opensandbox_cli.commands.command import command_group, exec_cmd
from opensandbox_cli.commands.config_cmd import config_group
from opensandbox_cli.commands.file import file_group
from opensandbox_cli.commands.sandbox import sandbox_group
from opensandbox_cli.config import resolve_config
from opensandbox_cli.output import OutputFormatter


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--api-key", envvar="OPEN_SANDBOX_API_KEY", default=None, help="API 认证密钥。")
@click.option("--domain", envvar="OPEN_SANDBOX_DOMAIN", default=None, help="API 服务器域名（如 localhost:8080）。")
@click.option("--protocol", type=click.Choice(["http", "https"]), default=None, help="通信协议（http/https）。")
@click.option("--timeout", "request_timeout", type=int, default=None, help="请求超时时间（秒）。")
@click.option("-o", "--output", "output_format", type=click.Choice(["table", "json", "yaml"]), default=None, help="输出格式。")
@click.option("--config", "config_path", type=click.Path(exists=False, path_type=Path), default=None, help="配置文件路径。")
@click.option("-v", "--verbose", is_flag=True, default=False, help="启用调试/详细输出。")
@click.option("--no-color", is_flag=True, default=False, help="禁用彩色输出。")
@click.version_option(version=__version__, prog_name="opensandbox")
@click.pass_context
def cli(
    ctx: click.Context,
    api_key: str | None,
    domain: str | None,
    protocol: str | None,
    request_timeout: int | None,
    output_format: str | None,
    config_path: Path | None,
    verbose: bool,
    no_color: bool,
) -> None:
    """OpenSandbox CLI — 从终端管理沙盒。

    OpenSandbox CLI 提供了完整的沙盒管理能力，包括：
    - 沙盒创建、查询、删除
    - 命令执行和代码运行
    - 文件上传下载
    - 配置管理

    使用示例：
        # 查看帮助
        osb --help

        # 创建沙盒
        osb sandbox create -i python:3.11

        # 执行命令
        osb exec <sandbox-id> ls -la

        # 查看配置
        osb config show
    """
    # 启用调试日志
    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    # 解析配置（合并 CLI 参数、环境变量、配置文件）
    resolved = resolve_config(
        cli_api_key=api_key,
        cli_domain=domain,
        cli_protocol=protocol,
        cli_timeout=request_timeout,
        cli_output=output_format,
        config_path=config_path,
    )

    # 创建输出格式化工具
    formatter = OutputFormatter(
        resolved["output_format"],
        color=not no_color and resolved.get("color", True),
    )

    # 创建客户端上下文并存储到 click context
    ctx.obj = ClientContext(resolved_config=resolved, output=formatter)
    # 注册关闭回调，确保资源正确释放
    ctx.call_on_close(lambda: ctx.obj.close())


# 注册子命令组
cli.add_command(sandbox_group)
cli.add_command(command_group)
cli.add_command(exec_cmd)
cli.add_command(file_group)
cli.add_command(code_group)
cli.add_command(config_group)
