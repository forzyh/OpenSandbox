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

"""CLI 输出格式化工具测试模块。

本模块测试 opensandbox_cli.output 模块的 OutputFormatter 类，包括：
1. JSON 格式输出
2. YAML 格式输出
3. 表格格式输出
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from opensandbox_cli.output import OutputFormatter


# ---------------------------------------------------------------------------
# 测试用模型
# ---------------------------------------------------------------------------


class FakeItem(BaseModel):
    """测试用的 Pydantic 模型。

    用于测试 OutputFormatter 的模型序列化和格式化功能。
    """
    id: str
    name: str
    score: int


# ---------------------------------------------------------------------------
# JSON 输出测试
# ---------------------------------------------------------------------------


class TestJsonOutput:
    """JSON 格式输出测试类。

    测试 OutputFormatter 的 JSON 格式化功能。
    """

    def test_print_dict(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试字典的 JSON 输出。

        验证 print_dict 方法能正确输出 JSON 格式。
        """
        fmt = OutputFormatter("json", color=False)
        fmt.print_dict({"key": "value", "num": 42})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == {"key": "value", "num": 42}

    def test_print_model(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试模型的 JSON 输出。

        验证 print_model 方法能正确序列化并输出 Pydantic 模型。
        """
        fmt = OutputFormatter("json", color=False)
        item = FakeItem(id="abc", name="test", score=100)
        fmt.print_model(item)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["id"] == "abc"
        assert data["name"] == "test"
        assert data["score"] == 100

    def test_print_models(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试模型列表的 JSON 输出。

        验证 print_models 方法能正确输出模型列表的 JSON 数组。
        """
        fmt = OutputFormatter("json", color=False)
        items = [
            FakeItem(id="1", name="a", score=10),
            FakeItem(id="2", name="b", score=20),
        ]
        fmt.print_models(items, columns=["id", "name", "score"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) == 2
        assert data[0]["id"] == "1"
        assert data[1]["name"] == "b"


# ---------------------------------------------------------------------------
# YAML 输出测试
# ---------------------------------------------------------------------------


class TestYamlOutput:
    """YAML 格式输出测试类。

    测试 OutputFormatter 的 YAML 格式化功能。
    """

    def test_print_dict(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试字典的 YAML 输出。

        验证 print_dict 方法能正确输出 YAML 格式。
        """
        fmt = OutputFormatter("yaml", color=False)
        fmt.print_dict({"key": "value"})
        captured = capsys.readouterr()
        assert "key: value" in captured.out

    def test_print_model(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试模型的 YAML 输出。

        验证 print_model 方法能正确输出 Pydantic 模型的 YAML 格式。
        """
        fmt = OutputFormatter("yaml", color=False)
        item = FakeItem(id="x", name="y", score=5)
        fmt.print_model(item)
        captured = capsys.readouterr()
        assert "id: x" in captured.out
        assert "name: y" in captured.out
        assert "score: 5" in captured.out


# ---------------------------------------------------------------------------
# 表格输出测试
# ---------------------------------------------------------------------------


class TestTableOutput:
    """表格格式输出测试类。

    测试 OutputFormatter 的表格格式化功能。
    """

    def test_print_dict_contains_values(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试字典的表格输出包含值。

        验证 print_dict 方法输出的表格包含所有键值对。
        """
        fmt = OutputFormatter("table", color=False)
        fmt.print_dict({"host": "example.com", "port": 8080}, title="Config")
        captured = capsys.readouterr()
        assert "example.com" in captured.out
        assert "8080" in captured.out
        assert "Config" in captured.out

    def test_print_dict_none_renders_dash(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试 None 值在表格中显示为短横线。

        验证 None 值在表格输出中被渲染为 "-"。
        """
        fmt = OutputFormatter("table", color=False)
        fmt.print_dict({"key": None})
        captured = capsys.readouterr()
        assert "-" in captured.out

    def test_print_models_shows_headers(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试模型列表的表格输出显示表头。

        验证 print_models 方法输出的表格包含指定的列头。
        """
        fmt = OutputFormatter("table", color=False)
        items = [FakeItem(id="1", name="a", score=10)]
        fmt.print_models(items, columns=["id", "name", "score"], title="Items")
        captured = capsys.readouterr()
        assert "ID" in captured.out
        assert "NAME" in captured.out
        assert "SCORE" in captured.out

    def test_print_text_ignores_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        """测试 print_text 忽略格式设置。

        验证 print_text 方法直接输出原始文本，不受格式设置影响。
        """
        fmt = OutputFormatter("json", color=False)
        fmt.print_text("hello world")
        captured = capsys.readouterr()
        assert captured.out.strip() == "hello world"
