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

"""CLI 配置加载和优先级合并测试模块。

本模块测试 opensandbox_cli.config 模块的功能，包括：
1. load_config_file: 配置文件加载
2. resolve_config: 配置优先级合并
3. init_config_file: 配置文件初始化

配置优先级（从高到低）：
1. CLI 命令行参数
2. 环境变量
3. 配置文件
4. SDK 默认值
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opensandbox_cli.config import (
    DEFAULT_CONFIG_TEMPLATE,
    init_config_file,
    load_config_file,
    resolve_config,
)


# ---------------------------------------------------------------------------
# load_config_file 测试
# ---------------------------------------------------------------------------


class TestLoadConfigFile:
    """配置文件加载测试类。

    测试 TOML 配置文件的加载和解析功能。
    """

    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        """测试文件不存在时返回空字典。

        验证当配置文件不存在时，函数返回空字典而非抛出异常。
        """
        result = load_config_file(tmp_path / "nonexistent.toml")
        assert result == {}

    def test_parses_toml_file(self, tmp_path: Path) -> None:
        """测试解析 TOML 文件。

        验证能正确解析 TOML 配置文件的基本结构。
        """
        cfg = tmp_path / "config.toml"
        cfg.write_text('[connection]\napi_key = "abc"\ndomain = "example.com"\n')
        result = load_config_file(cfg)
        assert result["connection"]["api_key"] == "abc"
        assert result["connection"]["domain"] == "example.com"

    def test_parses_all_sections(self, tmp_path: Path) -> None:
        """测试解析所有配置段。

        验证能正确解析 connection、output、defaults 所有段。
        """
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[connection]\napi_key = "k"\n\n'
            '[output]\nformat = "json"\ncolor = false\n\n'
            '[defaults]\nimage = "alpine"\ntimeout = "5m"\n'
        )
        result = load_config_file(cfg)
        assert result["output"]["format"] == "json"
        assert result["output"]["color"] is False
        assert result["defaults"]["image"] == "alpine"
        assert result["defaults"]["timeout"] == "5m"


# ---------------------------------------------------------------------------
# resolve_config 优先级测试：CLI > env > file > defaults
# ---------------------------------------------------------------------------


class TestResolveConfig:
    """配置解析和优先级合并测试类。

    测试配置源的优先级合并逻辑。
    """

    def test_defaults_when_nothing_configured(self, tmp_path: Path) -> None:
        """测试没有任何配置时的默认值。

        验证当没有配置任何值时，返回正确的默认值。
        """
        cfg_path = tmp_path / "empty.toml"
        cfg_path.write_text("")
        result = resolve_config(config_path=cfg_path)
        assert result["api_key"] is None
        assert result["domain"] is None
        assert result["protocol"] == "http"
        assert result["request_timeout"] == 30
        assert result["output_format"] == "table"
        assert result["color"] is True

    def test_file_values_override_defaults(self, tmp_path: Path) -> None:
        """测试配置文件值覆盖默认值。

        验证配置文件中的值能正确覆盖 SDK 默认值。
        """
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[connection]\napi_key = "file-key"\ndomain = "file.host"\n'
            'protocol = "https"\nrequest_timeout = 60\n\n'
            '[output]\nformat = "json"\ncolor = false\n\n'
            '[defaults]\nimage = "node:20"\ntimeout = "15m"\n'
        )
        result = resolve_config(config_path=cfg)
        assert result["api_key"] == "file-key"
        assert result["domain"] == "file.host"
        assert result["protocol"] == "https"
        assert result["request_timeout"] == 60
        assert result["output_format"] == "json"
        assert result["color"] is False
        assert result["default_image"] == "node:20"
        assert result["default_timeout"] == "15m"

    def test_env_overrides_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试环境变量覆盖配置文件值。

        验证环境变量的优先级高于配置文件。
        """
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[connection]\napi_key = "file-key"\ndomain = "file.host"\n'
        )

        monkeypatch.setenv("OPEN_SANDBOX_API_KEY", "env-key")
        monkeypatch.setenv("OPEN_SANDBOX_DOMAIN", "env.host")
        monkeypatch.setenv("OPEN_SANDBOX_PROTOCOL", "https")
        monkeypatch.setenv("OPEN_SANDBOX_REQUEST_TIMEOUT", "120")
        monkeypatch.setenv("OPEN_SANDBOX_OUTPUT", "yaml")

        result = resolve_config(config_path=cfg)
        assert result["api_key"] == "env-key"
        assert result["domain"] == "env.host"
        assert result["protocol"] == "https"
        assert result["request_timeout"] == 120
        assert result["output_format"] == "yaml"

    def test_cli_overrides_everything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试 CLI 参数覆盖所有其他配置源。

        验证 CLI 参数具有最高优先级。
        """
        cfg = tmp_path / "config.toml"
        cfg.write_text('[connection]\napi_key = "file-key"\n')
        monkeypatch.setenv("OPEN_SANDBOX_API_KEY", "env-key")

        result = resolve_config(
            cli_api_key="cli-key",
            cli_domain="cli.host",
            cli_protocol="https",
            cli_timeout=999,
            cli_output="yaml",
            config_path=cfg,
        )
        assert result["api_key"] == "cli-key"
        assert result["domain"] == "cli.host"
        assert result["protocol"] == "https"
        assert result["request_timeout"] == 999
        assert result["output_format"] == "yaml"

    def test_invalid_timeout_env_falls_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试无效环境变量值回退到默认值。

        验证当环境变量值无法解析时，能正确回退到默认值。
        """
        cfg = tmp_path / "empty.toml"
        cfg.write_text("")
        monkeypatch.setenv("OPEN_SANDBOX_REQUEST_TIMEOUT", "not-a-number")
        result = resolve_config(config_path=cfg)
        # 回退到默认值 30
        assert result["request_timeout"] == 30


# ---------------------------------------------------------------------------
# init_config_file 测试
# ---------------------------------------------------------------------------


class TestInitConfigFile:
    """配置文件初始化测试类。

    测试配置文件的创建和覆盖功能。
    """

    def test_creates_default_config(self, tmp_path: Path) -> None:
        """测试创建默认配置文件。

        验证能在指定路径创建包含模板内容的配置文件。
        """
        cfg_path = tmp_path / ".opensandbox" / "config.toml"
        result = init_config_file(cfg_path)
        assert result == cfg_path
        assert cfg_path.exists()
        content = cfg_path.read_text()
        assert "[connection]" in content
        assert "[output]" in content
        assert "[defaults]" in content

    def test_refuses_overwrite_without_force(self, tmp_path: Path) -> None:
        """测试拒绝覆盖已存在的文件。

        验证当文件已存在且未指定 force 时，抛出 FileExistsError。
        """
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text("existing")
        with pytest.raises(FileExistsError, match="already exists"):
            init_config_file(cfg_path)

    def test_force_overwrites(self, tmp_path: Path) -> None:
        """测试强制覆盖已存在的文件。

        验证使用 force=True 能覆盖已存在的文件。
        """
        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text("old content")
        init_config_file(cfg_path, force=True)
        assert cfg_path.read_text() == DEFAULT_CONFIG_TEMPLATE

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """测试创建父目录。

        验证当父目录不存在时，能自动创建完整的目录结构。
        """
        cfg_path = tmp_path / "a" / "b" / "c" / "config.toml"
        init_config_file(cfg_path)
        assert cfg_path.exists()
