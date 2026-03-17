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

"""CLI 工具函数测试模块。

本模块测试 opensandbox_cli.utils 模块的功能，包括：
1. parse_duration: 时间 duration 字符串解析
2. DurationType: Click 时间参数类型
3. KeyValueType: Click 键值对参数类型
"""

from __future__ import annotations

from datetime import timedelta

import click
import pytest

from opensandbox_cli.utils import DURATION, KEY_VALUE, parse_duration


# ---------------------------------------------------------------------------
# parse_duration 测试
# ---------------------------------------------------------------------------


class TestParseDuration:
    """时间 duration 解析测试类。

    测试 parse_duration 函数对各种时间格式的支持。
    """

    @pytest.mark.parametrize(
        "input_str, expected",
        [
            ("10", timedelta(seconds=10)),           # 纯数字（秒）
            ("0", timedelta(seconds=0)),             # 零
            ("10s", timedelta(seconds=10)),          # 秒
            ("5m", timedelta(minutes=5)),            # 分钟
            ("2h", timedelta(hours=2)),              # 小时
            ("1h30m", timedelta(hours=1, minutes=30)),  # 小时 + 分钟
            ("1h30m45s", timedelta(hours=1, minutes=30, seconds=45)),  # 完整格式
            ("90s", timedelta(seconds=90)),          # 超过 60 秒
        ],
    )
    def test_valid_durations(
        self, input_str: str, expected: timedelta
    ) -> None:
        """测试有效的时间格式解析。

        参数化测试各种有效的时间格式。

        参数：
            input_str: 输入的时间字符串
            expected: 期望的 timedelta 结果
        """
        assert parse_duration(input_str) == expected

    @pytest.mark.parametrize(
        "input_str",
        [
            "",        # 空字符串
            "abc",     # 无效字符
            "10x",     # 无效单位
            "m10",     # 顺序错误
            "-5m",     # 负数
        ],
    )
    def test_invalid_durations(self, input_str: str) -> None:
        """测试无效的时间格式。

        参数化测试各种无效的时间格式，验证抛出 BadParameter 异常。

        参数：
            input_str: 输入的时间字符串
        """
        with pytest.raises(click.BadParameter):
            parse_duration(input_str)

    def test_strips_whitespace(self) -> None:
        """测试去除前后空白字符。

        验证输入字符串的前后空白字符会被正确去除。
        """
        assert parse_duration("  10m  ") == timedelta(minutes=10)


# ---------------------------------------------------------------------------
# DurationType (Click 参数类型) 测试
# ---------------------------------------------------------------------------


class TestDurationType:
    """Click DurationType 参数类型测试类。

    测试 DurationType 在 Click 命令中的使用。
    """

    def test_converts_string(self) -> None:
        """测试字符串转换。

        验证能将时间字符串转换为 timedelta 对象。
        """
        result = DURATION.convert("5m", None, None)
        assert result == timedelta(minutes=5)

    def test_passes_through_timedelta(self) -> None:
        """测试 timedelta 透传。

        验证如果输入已经是 timedelta，直接返回。
        """
        td = timedelta(hours=1)
        result = DURATION.convert(td, None, None)  # type: ignore[arg-type]
        assert result is td

    def test_invalid_raises_bad_parameter(self) -> None:
        """测试无效输入抛出异常。

        验证无效输入会抛出 click.BadParameter 异常。
        """
        with pytest.raises(click.exceptions.BadParameter):
            DURATION.convert("invalid", None, None)


# ---------------------------------------------------------------------------
# KeyValueType (Click 参数类型) 测试
# ---------------------------------------------------------------------------


class TestKeyValueType:
    """Click KeyValueType 参数类型测试类。

    测试 KeyValueType 解析 KEY=VALUE 格式的功能。
    """

    def test_parses_simple_kv(self) -> None:
        """测试简单的键值对解析。

        验证基本的 KEY=VALUE 格式能正确解析。
        """
        assert KEY_VALUE.convert("FOO=bar", None, None) == ("FOO", "bar")

    def test_value_can_contain_equals(self) -> None:
        """测试值中包含等号的情况。

        验证当值中包含等号时，只有第一个等号被用作分隔符。
        """
        assert KEY_VALUE.convert("key=a=b=c", None, None) == ("key", "a=b=c")

    def test_empty_value(self) -> None:
        """测试空值的情况。

        验证 KEY= 格式能被正确解析为 (key, "")。
        """
        assert KEY_VALUE.convert("key=", None, None) == ("key", "")

    def test_missing_equals_fails(self) -> None:
        """测试缺少等号的情况。

        验证没有等号的输入会抛出异常。
        """
        with pytest.raises(click.exceptions.BadParameter):
            KEY_VALUE.convert("no-equals", None, None)

    def test_passes_through_tuple(self) -> None:
        """测试元组透传。

        验证如果输入已经是元组，直接返回。
        """
        t = ("key", "val")
        result = KEY_VALUE.convert(t, None, None)  # type: ignore[arg-type]
        assert result is t
