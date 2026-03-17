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

"""共享 CLI 工具函数和类型模块。

本模块提供了 CLI 命令中常用的工具函数和 Click 参数类型：

1. 时间 duration 解析：
   - parse_duration: 解析人类友好的时间字符串（如 "10m", "1h30m"）
   - DurationType: Click 参数类型，用于解析时间 duration

2. 键值对解析：
   - KeyValueType: Click 参数类型，用于解析 KEY=VALUE 格式

3. 错误处理：
   - handle_errors: 装饰器，用于统一处理命令中的异常

使用示例：
    from opensandbox_cli.utils import DURATION, KEY_VALUE, handle_errors

    @click.option("-t", "--timeout", type=DURATION)
    @click.option("--env", multiple=True, type=KEY_VALUE)
    @handle_errors
    def my_command(timeout, env):
        pass
"""

from __future__ import annotations

import functools
import re
import sys
from datetime import timedelta

import click


# ---------------------------------------------------------------------------
# 时间 duration 解析（如 "10m", "1h30m", "90s", "2h"）
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$"
)


def parse_duration(value: str) -> timedelta:
    """解析人类友好的时间 duration 字符串为 timedelta 对象。

    支持的时间格式：
    - 纯数字：视为秒数（如 "10" 表示 10 秒）
    - 秒：如 "90s"
    - 分钟：如 "10m"
    - 小时：如 "2h"
    - 组合格式：如 "1h30m", "1h30m45s"

    参数：
        value: 时间 duration 字符串

    返回：
        timedelta: 解析后的时间对象

    异常：
        click.BadParameter: 当输入格式无效时

    使用示例：
        parse_duration("10m")      # timedelta(minutes=10)
        parse_duration("1h30m")    # timedelta(hours=1, minutes=30)
        parse_duration("90s")      # timedelta(seconds=90)
        parse_duration("1h30m45s") # timedelta(hours=1, minutes=30, seconds=45)
    """
    value = value.strip()
    if not value:
        raise click.BadParameter("Duration cannot be empty")

    # 纯数字视为秒数
    if value.isdigit():
        return timedelta(seconds=int(value))

    m = _DURATION_RE.match(value)
    if not m or not m.group(0):
        raise click.BadParameter(
            f"Invalid duration '{value}'. Use format like 10m, 1h30m, 90s."
        )

    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    seconds = int(m.group("seconds") or 0)
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


class DurationType(click.ParamType):
    """Click 参数类型：时间 duration 解析器。

    用于 Click 命令的选项参数，将用户输入的时间字符串转换为 timedelta 对象。

    属性：
        name: 类型名称，用于帮助信息显示

    使用示例：
        @click.option("-t", "--timeout", type=DurationType())
        def my_command(timeout: timedelta):
            pass
    """

    name = "duration"

    def convert(
        self, value: str, param: click.Parameter | None, ctx: click.Context | None
    ) -> timedelta:
        """转换输入值为 timedelta 对象。

        参数：
            value: 输入值
            param: Click 参数对象
            ctx: Click 上下文

        返回：
            timedelta: 转换后的时间对象

        异常：
            click.BadParameter: 当转换失败时
        """
        if isinstance(value, timedelta):
            return value
        try:
            return parse_duration(value)
        except click.BadParameter:
            self.fail(
                f"Invalid duration '{value}'. Use format like 10m, 1h30m, 90s.",
                param,
                ctx,
            )


# DurationType 实例，可直接在 Click 选项中使用
DURATION = DurationType()


# ---------------------------------------------------------------------------
# 键值对解析（如 --env FOO=bar）
# ---------------------------------------------------------------------------


class KeyValueType(click.ParamType):
    """Click 参数类型：KEY=VALUE 格式解析器。

    用于解析形如 "FOO=bar" 的键值对字符串，将其转换为 (key, value) 元组。
    值中可以包含等号（如 "key=a=b=c" 会被解析为 ("key", "a=b=c")）。

    属性：
        name: 类型名称，用于帮助信息显示

    使用示例：
        @click.option("--env", multiple=True, type=KeyValueType())
        def my_command(env: tuple[tuple[str, str], ...]):
            # env = (("FOO", "bar"), ("BAZ", "qux"))
            pass
    """

    name = "KEY=VALUE"

    def convert(
        self, value: str, param: click.Parameter | None, ctx: click.Context | None
    ) -> tuple[str, str]:
        """转换输入字符串为 (key, value) 元组。

        参数：
            value: 输入字符串（格式：KEY=VALUE）
            param: Click 参数对象
            ctx: Click 上下文

        返回：
            tuple[str, str]: (key, value) 元组

        异常：
            click.BadParameter: 当输入不包含等号时
        """
        if isinstance(value, tuple):
            return value
        if "=" not in value:
            self.fail(f"Expected KEY=VALUE format, got '{value}'", param, ctx)
        key, _, val = value.partition("=")
        return (key, val)


# KeyValueType 实例，可直接在 Click 选项中使用
KEY_VALUE = KeyValueType()


# ---------------------------------------------------------------------------
# 错误处理装饰器
# ---------------------------------------------------------------------------


def handle_errors(fn):  # type: ignore[no-untyped-def]
    """错误处理装饰器。

    该装饰器包装命令函数，捕获并优雅地处理 SDK/HTTP 异常，
    将错误信息以友好的方式输出给用户。

    处理的异常类型：
    - click.exceptions.Exit: 直接重新抛出（已处理的退出）
    - click.ClickException: 直接重新抛出（Click 已处理的异常）
    - SandboxException: 输出错误信息并退出
    - 其他 Exception: 输出错误信息并退出

    参数：
        fn: 被装饰的函数

    返回：
        wrapper: 包装后的函数

    使用示例：
        @click.command()
        @handle_errors
        def my_command():
            # 如果此处抛出异常，会被捕获并输出友好错误信息
            risky_operation()
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return fn(*args, **kwargs)
        except click.exceptions.Exit:
            raise
        except click.ClickException:
            raise
        except Exception as exc:
            # 在此处导入以避免模块级别的循环导入
            from opensandbox.exceptions import SandboxException

            if isinstance(exc, SandboxException):
                click.secho(f"Error: {exc}", fg="red", err=True)
            else:
                click.secho(f"Error: {exc}", fg="red", err=True)
            sys.exit(1)

    return wrapper
