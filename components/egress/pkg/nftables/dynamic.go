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

// nftables 动态规则管理。
//
// 本文件定义用于动态 nftables 规则的数据结构和辅助函数，
// 主要用于将 DNS 解析的 IP 地址动态添加到允许集合。
package nftables

import (
	"fmt"
	"net/netip"
	"strings"
	"time"
)

// 动态集合配置常量
const (
	dynAllowV4Set  = "dyn_allow_v4"  // IPv4 动态允许集合名称
	dynAllowV6Set  = "dyn_allow_v6"  // IPv6 动态允许集合名称
	dynSetTimeoutS = 300             // 动态集合条目超时时间（秒）
	minTTLSec      = 60              // 最小 TTL（秒）
	maxTTLSec      = 300             // 最大 TTL（秒）
)

// ResolvedIP 表示从 DNS 解析得到的 IP 地址及其 TTL。
type ResolvedIP struct {
	Addr netip.Addr    // IP 地址
	TTL  time.Duration // DNS 记录的 TTL
}

// buildAddResolvedIPsScript 生成 nft 脚本片段，将解析的 IP 添加到动态允许集合。
//
// 参数：
//   table: nftables 表名
//   ips: 要添加的 IP 列表
//
// 返回：
//   nft 脚本字符串
func buildAddResolvedIPsScript(table string, ips []ResolvedIP) string {
	var v4, v6 []string
	for _, r := range ips {
		sec := clampTTL(r.TTL)
		if r.Addr.Is4() {
			v4 = append(v4, fmt.Sprintf("%s timeout %ds", r.Addr.String(), sec))
		} else if r.Addr.Is6() {
			v6 = append(v6, fmt.Sprintf("%s timeout %ds", r.Addr.String(), sec))
		}
	}
	var b strings.Builder
	if len(v4) > 0 {
		fmt.Fprintf(&b, "add element inet %s %s { %s }\n", table, dynAllowV4Set, strings.Join(v4, ", "))
	}
	if len(v6) > 0 {
		fmt.Fprintf(&b, "add element inet %s %s { %s }\n", table, dynAllowV6Set, strings.Join(v6, ", "))
	}
	return b.String()
}

// clampTTL 将 TTL 限制在允许范围内。
//
// 参数：
//   d: 原始 TTL
//
// 返回：
//   限制后的 TTL（秒）
func clampTTL(d time.Duration) int {
	sec := int(d.Seconds())
	if sec < minTTLSec {
		return minTTLSec
	}
	if sec > maxTTLSec {
		return maxTTLSec
	}
	return sec
}
