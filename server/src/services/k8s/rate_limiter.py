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
通用令牌桶速率限制器模块。

本模块提供了 TokenBucketRateLimiter 类，实现了线程安全的令牌桶算法，
用于限制对 Kubernetes API 等共享资源的访问频率。

令牌桶算法原理：
1. 桶中以 QPS（每秒请求数）的速率生成令牌
2. 桶有最大容量（burst），超过容量的令牌会被丢弃
3. 每次请求需要消耗一个令牌
4. 如果桶中没有令牌，请求会被阻塞直到有令牌可用

使用示例：
    >>> # 创建限流器：每秒 10 个令牌，最大突发 20 个
    >>> limiter = TokenBucketRateLimiter(qps=10.0, burst=20)
    >>> limiter.acquire()   # 阻塞直到获取到令牌
    >>> do_something()      # 执行操作
    >>>
    >>> # 非阻塞尝试
    >>> if limiter.try_acquire():
    ...     do_something()  # 有令牌，执行操作
    ... else:
    ...     skip()          # 无令牌，跳过或稍后重试
"""

import threading
import time


class TokenBucketRateLimiter:
    """
    线程安全的令牌桶速率限制器。

    令牌以 ``qps`` 令牌/秒的速度补充，最多补充到 ``burst`` 个令牌。
    调用 :meth:`acquire` 会消耗一个令牌，如果桶为空则阻塞等待。

    特性：
    - 线程安全：使用锁保护令牌桶状态
    - 精确计时：使用 time.monotonic() 避免时钟跳变影响
    - 灵活配置：支持自定义 QPS 和突发容量

    Args:
        qps: 持续请求速率，单位为每秒请求数（Queries Per Second）
        burst: 最大突发大小（桶容量）。默认为 ``qps``，
               最小值为 1，确保无论 qps 多小都至少有一个令牌可用

    Attributes:
        _qps: 每秒令牌生成速率
        _burst: 桶容量（最大令牌数）
        _tokens: 当前令牌数量
        _last_refill: 上次补充令牌的时间
        _lock: 线程锁

    Examples:
        >>> # 限制为每秒 5 个请求，允许突发 10 个
        >>> limiter = TokenBucketRateLimiter(qps=5.0, burst=10)
        >>> for i in range(100):
        ...     limiter.acquire()
        ...     make_api_call()
    """

    def __init__(self, qps: float, burst: float = 0.0) -> None:
        """
        初始化令牌桶速率限制器。

        Args:
            qps: 每秒请求数（令牌生成速率）
            burst: 最大突发容量（桶容量）

        Raises:
            ValueError: 如果 qps 小于等于 0

        注意：
            - burst 为 0 时，默认等于 qps
            - burst 最小值为 1，确保桶始终能容纳至少一个令牌
        """
        if qps <= 0:
            raise ValueError(f"qps 必须大于 0，得到 {qps}")
        self._qps = qps
        # burst 默认为 qps，最小值为 1
        self._burst = max(burst if burst > 0 else qps, 1.0)
        self._tokens = self._burst  # 初始时桶是满的
        self._last_refill = time.monotonic()  # 使用单调时钟
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def acquire(self) -> None:
        """
        获取一个令牌，如果没有令牌则阻塞等待。

        该方法会阻塞直到获取到一个令牌。在极端情况下（qps 很低），
        可能需要等待较长时间。

        注意：
            - 最小睡眠时间为 1 毫秒，避免浮点数精度问题导致的忙等待
            - 该方法是线程安全的
        """
        while True:
            wait = self._try_acquire()
            if wait <= 0.0:
                return
            # 限制最小睡眠时间为 1 毫秒，避免浮点数精度问题导致的忙等待
            time.sleep(max(wait, 0.001))

    def try_acquire(self) -> bool:
        """
        尝试不阻塞地获取一个令牌。

        Returns:
            bool: 如果成功消耗令牌返回 True，如果桶为空返回 False

        Examples:
            >>> if limiter.try_acquire():
            ...     # 有令牌，执行操作
            ...     make_api_call()
            ... else:
            ...     # 无令牌，稍后重试或跳过
            ...     schedule_retry()
        """
        return self._try_acquire() <= 0.0

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _try_acquire(self) -> float:
        """
        尝试获取一个令牌。

        Returns:
            float: 如果成功获取令牌返回 0.0，
                   否则返回大约需要等待的秒数

        注意：该方法会在持有锁的情况下补充令牌。
        """
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            # 计算直到有一个令牌可用所需的时间
            return (1.0 - self._tokens) / self._qps

    def _refill(self) -> None:
        """
        根据经过的时间补充令牌（调用时必须持有锁）。

        补充逻辑：
        1. 计算自上次补充以来经过的时间
        2. 按 QPS 速率计算应生成的令牌数
        3. 更新令牌数量（不超过桶容量）
        4. 更新上次补充时间

        注意：该方法必须在持有 ``self._lock`` 的情况下调用。
        """
        now = time.monotonic()
        elapsed = now - self._last_refill
        # 补充令牌，不超过桶容量
        self._tokens = min(self._burst, self._tokens + elapsed * self._qps)
        self._last_refill = now
