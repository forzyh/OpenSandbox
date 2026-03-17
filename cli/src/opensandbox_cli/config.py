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

"""CLI 配置加载和管理模块。

本模块负责 CLI 配置的加载、解析和合并。配置来源按优先级（从高到低）包括：
1. CLI 命令行参数
2. 环境变量
3. 配置文件 (~/.opensandbox/config.toml)
4. SDK 默认值

主要功能：
- load_config_file: 加载 TOML 配置文件
- resolve_config: 合并所有配置源
- init_config_file: 创建默认配置文件

配置文件格式示例：
    [connection]
    api_key = "your-api-key"
    domain = "localhost:8080"
    protocol = "http"
    request_timeout = 30

    [output]
    format = "table"
    color = true

    [defaults]
    image = "python:3.11"
    timeout = "10m"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Python 3.11+ 使用内置 tomllib，否则尝试使用 tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None  # type: ignore[assignment]


# 默认配置文件路径
DEFAULT_CONFIG_DIR = Path.home() / ".opensandbox"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"

# 默认配置文件模板
DEFAULT_CONFIG_TEMPLATE = """\
# OpenSandbox CLI 配置文件
# 优先级：CLI 参数 > 环境变量 > 此文件 > SDK 默认值

[connection]
# api_key = "your-api-key"
# domain = "localhost:8080"
# protocol = "http"
# request_timeout = 30

[output]
# format = "table"    # table | json | yaml
# color = true

[defaults]
# image = "python:3.11"
# timeout = "10m"
"""


def load_config_file(config_path: Path | None = None) -> dict[str, Any]:
    """加载并解析 TOML 配置文件。

    读取指定路径的 TOML 配置文件并返回解析后的字典。
    如果文件不存在或 tomllib 不可用，返回空字典。

    参数：
        config_path: 配置文件路径（可选，默认为 DEFAULT_CONFIG_PATH）

    返回：
        dict[str, Any]: 解析后的配置字典

    异常处理：
        - 文件不存在：返回空字典
        - TOML 解析失败：抛出异常
        - tomllib 不可用：返回空字典
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return {}
    if tomllib is None:
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def resolve_config(
    *,
    cli_api_key: str | None = None,
    cli_domain: str | None = None,
    cli_protocol: str | None = None,
    cli_timeout: int | None = None,
    cli_output: str | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """合并所有配置源并返回扁平化的配置字典。

    按照优先级顺序合并配置：
    1. CLI 参数（最高优先级）
    2. 环境变量
    3. 配置文件
    4. SDK 默认值（最低优先级）

    参数：
        cli_api_key: CLI 传入的 API 密钥
        cli_domain: CLI 传入的域名
        cli_protocol: CLI 传入的协议
        cli_timeout: CLI 传入的超时时间（秒）
        cli_output: CLI 传入的输出格式
        config_path: 配置文件路径

    返回：
        dict[str, Any]: 合并后的配置字典，包含以下键：
            - api_key: API 认证密钥
            - domain: API 服务器域名
            - protocol: 通信协议（http/https）
            - request_timeout: 请求超时（秒）
            - output_format: 输出格式（table/json/yaml）
            - color: 是否启用彩色输出
            - default_image: 默认镜像
            - default_timeout: 默认超时
    """
    file_cfg = load_config_file(config_path)
    conn = file_cfg.get("connection", {})
    output_cfg = file_cfg.get("output", {})
    defaults = file_cfg.get("defaults", {})

    return {
        "api_key": cli_api_key
        or os.getenv("OPEN_SANDBOX_API_KEY")
        or conn.get("api_key"),
        "domain": cli_domain
        or os.getenv("OPEN_SANDBOX_DOMAIN")
        or conn.get("domain"),
        "protocol": cli_protocol
        or os.getenv("OPEN_SANDBOX_PROTOCOL")
        or conn.get("protocol")
        or "http",
        "request_timeout": cli_timeout
        or _int_or_none(os.getenv("OPEN_SANDBOX_REQUEST_TIMEOUT"))
        or conn.get("request_timeout")
        or 30,
        "output_format": cli_output
        or os.getenv("OPEN_SANDBOX_OUTPUT")
        or output_cfg.get("format")
        or "table",
        "color": output_cfg.get("color", True),
        "default_image": defaults.get("image"),
        "default_timeout": defaults.get("timeout"),
    }


def init_config_file(config_path: Path | None = None, *, force: bool = False) -> Path:
    """创建默认配置文件。

    在指定路径或默认位置创建包含模板内容的配置文件。

    参数：
        config_path: 配置文件路径（可选，默认为 ~/.opensandbox/config.toml）
        force: 是否强制覆盖已存在的文件

    返回：
        Path: 创建的配置文件路径

    异常：
        FileExistsError: 文件已存在且未指定 force=True
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if path.exists() and not force:
        raise FileExistsError(
            f"Config file already exists at {path}. Use --force to overwrite."
        )
    # 确保父目录存在
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEMPLATE)
    return path


def _int_or_none(value: str | None) -> int | None:
    """安全地将字符串转换为整数。

    尝试将字符串转换为整数，如果转换失败则返回 None。

    参数：
        value: 要转换的字符串值

    返回：
        int | None: 转换后的整数，或 None（如果输入为 None 或转换失败）
    """
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
