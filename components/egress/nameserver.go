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

// Nameserver IP 解析和验证。
//
// 本文件提供从 resolv.conf 解析 nameserver IP 的功能，
// 用于在 dns+nft 模式下将系统 DNS 服务器 IP 添加到 nftables 白名单。
package main

import (
	"net/netip"
	"os"
	"strconv"

	"github.com/alibaba/opensandbox/egress/pkg/constants"
	"github.com/alibaba/opensandbox/egress/pkg/dnsproxy"
	"github.com/alibaba/opensandbox/egress/pkg/log"
)

// AllowIPsForNft 解析并返回要合并到 nftables 允许集合的 IP 列表。
//
// 该函数用于 dns+nft 模式下，确保 DNS 流量能够正常工作：
// 1. 添加 127.0.0.1（代理监听地址/iptables 重定向目标）
// 2. 从 resolv.conf 解析 nameserver IP，并进行验证和数量限制
//
// 验证规则：
// - 跳过未指定的地址（0.0.0.0, ::）
// - 跳过回环地址（127.x, ::1）
//
// 数量限制：
// - 默认最多 3 个 nameserver
// - 可通过 EGRESS_MAX_NAMESERVERS=0 禁用限制
// - 可设置 1-10 之间的值
//
// 参数：
//   resolvPath: resolv.conf 文件路径
//
// 返回：
//   要添加到 nftables 允许集合的 IP 列表
func AllowIPsForNft(resolvPath string) []netip.Addr {
	// 从 resolv.conf 解析 nameserver IP
	raw, _ := dnsproxy.ResolvNameserverIPs(resolvPath)
	// 获取 nameserver 数量限制
	maxNsCount := maxNameserversFromEnv()

	// 验证 IP 地址
	var validated []netip.Addr
	for _, ip := range raw {
		if maxNsCount > 0 && len(validated) >= maxNsCount {
			break
		}
		if !isValidNameserverIP(ip) {
			continue
		}
		validated = append(validated, ip)
	}

	// 127.0.0.1 放在最前面，确保被重定向到代理的流量能被 nftables 接受
	out := make([]netip.Addr, 0, 1+len(validated))
	out = append(out, netip.MustParseAddr("127.0.0.1"))
	out = append(out, validated...)

	if len(out) > 1 {
		log.Infof("[dns] whitelisting proxy listen + %d nameserver(s) for nft: %v", len(validated), formatIPs(out))
	} else {
		log.Infof("[dns] whitelisting proxy listen (127.0.0.1); no valid nameserver IPs from %s", resolvPath)
	}
	return out
}

// maxNameserversFromEnv 从环境变量获取 nameserver 数量限制。
//
// 环境变量：OPENSANDBOX_EGRESS_MAX_NS
// - 空值或无效值：返回默认值 3
// - 0：无限制
// - 1-10：指定限制
// - >10：限制为 10
//
// 返回：
//   nameserver 数量限制（0 表示无限制）
func maxNameserversFromEnv() int {
	s := os.Getenv(constants.EnvMaxNameservers)
	if s == "" {
		return constants.DefaultMaxNameservers
	}
	n, err := strconv.Atoi(s)
	if err != nil || n < 0 {
		return constants.DefaultMaxNameservers
	}
	if n > 10 {
		return 10
	}
	// 0 = 无限制
	return n
}

// isValidNameserverIP 检查 IP 是否是有效的 nameserver 地址。
//
// 无效的地址包括：
// - 未指定地址（0.0.0.0, ::）
// - 回环地址（127.0.0.1, ::1 等）
//
// 参数：
//   ip: 要检查的 IP 地址
//
// 返回：
//   如果是有效的 nameserver IP 返回 true
func isValidNameserverIP(ip netip.Addr) bool {
	if ip.IsUnspecified() {
		return false
	}
	if ip.IsLoopback() {
		return false
	}
	return true
}

// formatIPs 将 IP 地址列表转换为字符串列表。
//
// 参数：
//   ips: IP 地址列表
//
// 返回：
//   字符串格式的 IP 列表
func formatIPs(ips []netip.Addr) []string {
	out := make([]string, len(ips))
	for i, ip := range ips {
		out[i] = ip.String()
	}
	return out
}
