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

// nftables 相关配置和设置。
//
// 本文件包含 nftables 相关的辅助函数，用于：
// 1. 创建 nftables 管理器
// 2. 解析 nftables 配置选项
// 3. 设置 nftables 静态策略和动态 DNS 解析 IP
package main

import (
	"context"
	"net/netip"
	"os"
	"strings"

	"github.com/alibaba/opensandbox/egress/pkg/constants"
	"github.com/alibaba/opensandbox/egress/pkg/dnsproxy"
	"github.com/alibaba/opensandbox/egress/pkg/log"
	"github.com/alibaba/opensandbox/egress/pkg/nftables"
	"github.com/alibaba/opensandbox/egress/pkg/policy"
)

// nftApplier 定义了 nftables 策略应用的接口。
//
// 该接口用于抽象 nftables 操作，便于测试和模式切换。
type nftApplier interface {
	// ApplyStatic 应用静态网络策略到 nftables
	ApplyStatic(context.Context, *policy.NetworkPolicy) error
	// AddResolvedIPs 将 DNS 解析的 IP 添加到动态允许集合
	AddResolvedIPs(context.Context, []nftables.ResolvedIP) error
}

// createNftManager 创建 nftables 管理器。
//
// 仅在 dns+nft 模式下返回实际的 Manager 实例，
// dns-only 模式返回 nil。
//
// 参数：
//   mode: 运行模式（"dns" 或 "dns+nft"）
//
// 返回：
//   nftables 管理器实例，dns-only 模式下返回 nil
func createNftManager(mode string) nftApplier {
	if mode != constants.PolicyDnsNft {
		return nil
	}
	return nftables.NewManagerWithOptions(parseNftOptions())
}

// setupNft 配置 nftables 静态策略并连接 DNS 解析回调。
//
// 该函数在 dns+nft 模式下执行以下操作：
// 1. 将初始策略应用到 nftables
// 2. 将 nameserver IP 合并到允许集合（确保系统 DNS 可用）
// 3. 设置 DNS 解析回调，将解析的 IP 动态添加到 nftables
//
// 参数：
//   ctx: 上下文
//   nftMgr: nftables 管理器
//   initialPolicy: 初始网络策略
//   proxy: DNS 代理实例
//   nameserverIPs: nameserver IP 列表，用于合并到允许集合
func setupNft(ctx context.Context, nftMgr nftApplier, initialPolicy *policy.NetworkPolicy, proxy *dnsproxy.Proxy, nameserverIPs []netip.Addr) {
	if nftMgr == nil {
		log.Warnf("nftables disabled (dns-only mode)")
		return
	}
	log.Infof("applying nftables static policy (dns+nft mode) with %d nameserver IP(s) merged into allow set", len(nameserverIPs))

	// 将 nameserver IP 添加到策略的允许列表中
	policyWithNS := initialPolicy.WithExtraAllowIPs(nameserverIPs)

	// 应用静态策略到 nftables
	if err := nftMgr.ApplyStatic(ctx, policyWithNS); err != nil {
		log.Fatalf("nftables static apply failed: %v", err)
	}
	log.Infof("nftables static policy applied (table inet opensandbox); DNS-resolved IPs will be added to dynamic allow sets")

	// 设置 DNS 解析回调：当域名解析成功时，将解析的 IP 添加到 nftables 动态允许集合
	proxy.SetOnResolved(func(domain string, ips []nftables.ResolvedIP) {
		if err := nftMgr.AddResolvedIPs(ctx, ips); err != nil {
			log.Warnf("[dns] add resolved IPs to nft failed for domain %q: %v", domain, err)
		}
	})
}

// parseNftOptions 从环境变量解析 nftables 配置选项。
//
// 支持的环境变量：
// - OPENSANDBOX_EGRESS_BLOCK_DOH_443: 是否阻止 DoH (DNS over HTTPS) 443 端口
// - OPENSANDBOX_EGRESS_DOH_BLOCKLIST: DoH 阻止列表（逗号分隔的 IP/CIDR）
//
// 返回：
//   nftables 配置选项
func parseNftOptions() nftables.Options {
	opts := nftables.Options{BlockDoT: true} // 默认阻止 DoT (DNS over TLS)

	// 检查是否阻止 DoH 443 端口
	if isTruthy(os.Getenv(constants.EnvBlockDoH443)) {
		opts.BlockDoH443 = true
	}

	// 解析 DoH 阻止列表
	if raw := os.Getenv(constants.EnvDoHBlocklist); strings.TrimSpace(raw) != "" {
		parts := strings.Split(raw, ",")
		for _, p := range parts {
			target := strings.TrimSpace(p)
			if target == "" {
				continue
			}
			// 尝试解析为单个 IP 地址
			if addr, err := netip.ParseAddr(target); err == nil {
				if addr.Is4() {
					opts.DoHBlocklistV4 = append(opts.DoHBlocklistV4, target)
				} else if addr.Is6() {
					opts.DoHBlocklistV6 = append(opts.DoHBlocklistV6, target)
				}
				continue
			}
			// 尝试解析为 CIDR 前缀
			if prefix, err := netip.ParsePrefix(target); err == nil {
				if prefix.Addr().Is4() {
					opts.DoHBlocklistV4 = append(opts.DoHBlocklistV4, target)
				} else if prefix.Addr().Is6() {
					opts.DoHBlocklistV6 = append(opts.DoHBlocklistV6, target)
				}
				continue
			}
			// 无效的条目，记录警告
			log.Warnf("ignoring invalid DoH blocklist entry: %s", target)
		}
	}
	return opts
}
