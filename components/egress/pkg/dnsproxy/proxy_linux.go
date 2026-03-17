// Copyright 2026 Alibaba Group Holding Ltd.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

//go:build linux

// Linux 专用的 DNS 代理实现。
//
// 本文件为 Linux 平台提供 SO_MARK 功能，使 iptables/nftables 能够识别
// 并绕过代理发出的 DNS 查询流量。
package dnsproxy

import (
	"net"
	"sync"
	"syscall"
	"time"

	"golang.org/x/sys/unix"

	"github.com/alibaba/opensandbox/egress/pkg/constants"
	"github.com/alibaba/opensandbox/egress/pkg/log"
)

// exemptDialerLogOnce 用于确保 exempt dialer 日志只打印一次
var exemptDialerLogOnce sync.Once

// dialerWithMark 创建带有 SO_MARK 设置的拨号器。
//
// SO_MARK 设置使 iptables 能够 RETURN 标记的数据包（绕过代理自身上游 DNS 查询的重定向）。
//
// 当上游 DNS 服务器在 nameserver exempt 列表中时，返回普通拨号器（不设置 mark），
// 这样上游流量遵循正常路由（如通过 tun）；iptables 仍然不会根据目标地址重定向这些流量。
//
// 参数：
//   p: DNS 代理实例
//
// 返回：
//   配置好的网络拨号器
func (p *Proxy) dialerWithMark() *net.Dialer {
	// 检查上游是否在 exempt 列表中
	if UpstreamInExemptList(p.UpstreamHost()) {
		exemptDialerLogOnce.Do(func() {
			log.Infof("[dns] upstream %s in nameserver exempt list, not setting SO_MARK", p.UpstreamHost())
		})
		return &net.Dialer{Timeout: 5 * time.Second}
	}

	// 设置 SO_MARK
	return &net.Dialer{
		Timeout: 5 * time.Second,
		Control: func(network, address string, c syscall.RawConn) error {
			var opErr error
			if err := c.Control(func(fd uintptr) {
				opErr = unix.SetsockoptInt(int(fd), unix.SOL_SOCKET, unix.SO_MARK, constants.MarkValue)
			}); err != nil {
				return err
			}
			return opErr
		},
	}
}
