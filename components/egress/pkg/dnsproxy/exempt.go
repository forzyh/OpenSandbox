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

// Nameserver exempt 列表管理。
//
// 本文件管理 nameserver exempt 列表，用于指定哪些 DNS 服务器
// 在代理发出查询时不设置 SO_MARK，使其遵循正常路由。
package dnsproxy

import (
	"net/netip"
	"os"
	"strings"
	"sync"

	"github.com/alibaba/opensandbox/egress/pkg/constants"
)

var (
	// exemptListOnce 确保 exempt 列表只解析一次
	exemptListOnce sync.Once
	// exemptAddrs 解析后的 exempt IP 列表
	exemptAddrs []netip.Addr
	// exemptSet 用于快速查找的 exempt IP 集合
	exemptSet map[netip.Addr]struct{}
)

// ParseNameserverExemptList 从环境变量解析 nameserver exempt 列表。
//
// 环境变量：OPENSANDBOX_EGRESS_NAMESERVER_EXEMPT（逗号分隔的 IP 列表）
// 只接受单个 IP 地址；无效或 CIDR 条目会被跳过。
// 结果会被缓存，避免重复解析。
//
// 用途：
// - nftables 允许集合
// - iptables 豁免规则
// - UpstreamInExemptList 快速查找
//
// 返回：
//   exempt IP 地址列表
func ParseNameserverExemptList() []netip.Addr {
	exemptListOnce.Do(func() { parseNameserverExemptListUncached() })
	return exemptAddrs
}

// parseNameserverExemptListUncached 解析 exempt 列表的实际实现（不检查缓存）。
func parseNameserverExemptListUncached() {
	raw := strings.TrimSpace(os.Getenv(constants.EnvNameserverExempt))
	if raw == "" {
		exemptAddrs = nil
		exemptSet = nil
		return
	}
	set := make(map[netip.Addr]struct{})
	var out []netip.Addr
	for _, s := range strings.Split(raw, ",") {
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		// 尝试解析为单个 IP 地址
		if addr, err := netip.ParseAddr(s); err == nil {
			// 去重
			if _, exists := set[addr]; exists {
				continue
			}
			set[addr] = struct{}{}
			out = append(out, addr)
		}
	}
	exemptAddrs = out
	exemptSet = set
}

// UpstreamInExemptList 检查上游 DNS 服务器是否在 exempt 列表中。
//
// 只进行精确的 IP 匹配。
// 当返回 true 时，代理不应设置 SO_MARK，使上游流量遵循正常路由（如通过 tun）。
//
// 参数：
//   upstreamHost: 上游 DNS 服务器的主机（IP 地址字符串）
//
// 返回：
//   如果上游在 exempt 列表中返回 true
func UpstreamInExemptList(upstreamHost string) bool {
	addr, err := netip.ParseAddr(upstreamHost)
	if err != nil {
		return false
	}
	ParseNameserverExemptList() // 确保缓存已初始化
	_, ok := exemptSet[addr]
	return ok
}
