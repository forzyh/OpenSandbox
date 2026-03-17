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

// nftables 管理器实现。
//
// 本文件实现 nftables 管理器，用于：
// 1. 应用静态 IP/CIDR 策略
// 2. 动态添加 DNS 解析的 IP 到允许集合
package nftables

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
	"sync"

	"github.com/alibaba/opensandbox/egress/pkg/constants"
	"github.com/alibaba/opensandbox/egress/pkg/log"
	"github.com/alibaba/opensandbox/egress/pkg/policy"
)

// nftables 配置常量
const (
	tableName     = "opensandbox" // nftables 表名
	chainName     = "egress"      // 链名称
	allowV4Set    = "allow_v4"    // 静态 IPv4 允许集合
	allowV6Set    = "allow_v6"    // 静态 IPv6 允许集合
	denyV4Set     = "deny_v4"     // 静态 IPv4 拒绝集合
	denyV6Set     = "deny_v6"     // 静态 IPv6 拒绝集合
	dohBlockV4Set = "doh_block_v4" // DoH IPv4 阻止集合
	dohBlockV6Set = "doh_block_v6" // DoH IPv6 阻止集合
)

// runner 定义 nft 命令执行函数类型。
type runner func(ctx context.Context, script string) ([]byte, error)

// Options 控制 nftables 执行的额外选项。
type Options struct {
	// BlockDoT 阻止 DNS-over-TLS（tcp/udp 853 端口）
	BlockDoT bool

	// BlockDoH443 阻止 DoH (DNS over HTTPS) 443 端口；
	// 当启用但 blocklist 为空时，阻止所有 443 端口
	BlockDoH443    bool
	DoHBlocklistV4 []string // DoH IPv4 阻止列表
	DoHBlocklistV6 []string // DoH IPv6 阻止列表
}

// Manager 管理 nftables 静态和动态规则。
type Manager struct {
	run  runner  // nft 命令执行函数
	opts Options // 配置选项
	mu   sync.Mutex // 保护并发访问
}

// NewManager 创建默认 nftables 管理器。
//
// 使用默认的 shell 执行器 `nft -f -`，默认启用 BlockDoT。
func NewManager() *Manager {
	return &Manager{run: defaultRunner, opts: Options{BlockDoT: true}}
}

// NewManagerWithRunner 创建带自定义执行器的管理器（用于测试）。
func NewManagerWithRunner(r runner) *Manager {
	return &Manager{run: r, opts: Options{BlockDoT: true}}
}

// NewManagerWithRunnerAndOptions 创建带自定义执行器和选项的管理器（用于测试）。
func NewManagerWithRunnerAndOptions(r runner, opts Options) *Manager {
	return &Manager{run: r, opts: opts}
}

// NewManagerWithOptions 创建带自定义选项的管理器（主程序使用）。
func NewManagerWithOptions(opts Options) *Manager {
	return &Manager{run: defaultRunner, opts: opts}
}

// ApplyStatic 将静态 IP/CIDR 策略应用到 nftables。
//
// 该函数会：
// 1. 删除并重建专用表/链
// 2. 创建静态允许/拒绝集合
// 3. 创建动态允许集合（带超时）
// 4. 配置规则链（包括 DoT/DoH 阻止）
//
// 使用互斥锁确保与 AddResolvedIPs 不重叠：
// 没有这个锁，add-element 可能在表被删除/重建时运行并失败，
// 导致已获准 DNS 响应的客户端遇到瞬态拒绝。
//
// 参数：
//   ctx: 上下文
//   p: 网络策略
//
// 返回：
//   应用错误（如有）
func (m *Manager) ApplyStatic(ctx context.Context, p *policy.NetworkPolicy) error {
	if p == nil {
		p = policy.DefaultDenyPolicy()
	}
	allowV4, allowV6, denyV4, denyV6 := p.StaticIPSets()
	log.Infof("nftables: applying static policy: default=%s, allow_v4=%d, allow_v6=%d, deny_v4=%d, deny_v6=%d",
		p.DefaultAction, len(allowV4), len(allowV6), len(denyV4), len(denyV6))

	m.mu.Lock()
	defer m.mu.Unlock()

	// 构建规则集脚本
	script := buildRuleset(p, m.opts)
	if _, err := m.run(ctx, script); err != nil {
		// 在新主机上 delete-table 可能失败；重试一次（不带 delete 行）
		if isMissingTableError(err) {
			fallback := removeDeleteTableLine(script)
			if fallback != script {
				if _, retryErr := m.run(ctx, fallback); retryErr == nil {
					return nil
				}
			}
		}
		return err
	}
	log.Infof("nftables: static policy applied successfully")
	return nil
}

// AddResolvedIPs 将 DNS 解析的 IP 添加到动态允许集合。
//
// TTL 会被限制在 minTTLSec 到 maxTTLSec 之间。
// 仅在表存在时调用（dns+nft 模式）。
//
// 参数：
//   ctx: 上下文
//   ips: 要添加的 IP 列表
//
// 返回：
//   添加错误（如有）
func (m *Manager) AddResolvedIPs(ctx context.Context, ips []ResolvedIP) error {
	if len(ips) == 0 {
		return nil
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	script := buildAddResolvedIPsScript(tableName, ips)
	if script == "" {
		return nil
	}
	log.Infof("nftables: adding %d resolved IP(s) to dynamic allow sets with script statement %s", len(ips), script)
	_, err := m.run(ctx, script)
	return err
}

// buildRuleset 构建完整的 nftables 规则集脚本。
func buildRuleset(p *policy.NetworkPolicy, opts Options) string {
	allowV4, allowV6, denyV4, denyV6 := p.StaticIPSets()

	var b strings.Builder

	// 重置并重建表、集合和链
	fmt.Fprintf(&b, "delete table inet %s\n", tableName)
	fmt.Fprintf(&b, "add table inet %s\n", tableName)

	// 创建静态集合
	fmt.Fprintf(&b, "add set inet %s %s { type ipv4_addr; flags interval; }\n", tableName, allowV4Set)
	fmt.Fprintf(&b, "add set inet %s %s { type ipv4_addr; flags interval; }\n", tableName, denyV4Set)
	fmt.Fprintf(&b, "add set inet %s %s { type ipv6_addr; flags interval; }\n", tableName, allowV6Set)
	fmt.Fprintf(&b, "add set inet %s %s { type ipv6_addr; flags interval; }\n", tableName, denyV6Set)

	// 创建动态集合（带超时）
	fmt.Fprintf(&b, "add set inet %s %s { type ipv4_addr; timeout %ds; }\n", tableName, dynAllowV4Set, dynSetTimeoutS)
	fmt.Fprintf(&b, "add set inet %s %s { type ipv6_addr; timeout %ds; }\n", tableName, dynAllowV6Set, dynSetTimeoutS)

	// 创建 DoH 阻止集合（如有配置）
	if len(opts.DoHBlocklistV4) > 0 {
		fmt.Fprintf(&b, "add set inet %s %s { type ipv4_addr; flags interval; }\n", tableName, dohBlockV4Set)
	}
	if len(opts.DoHBlocklistV6) > 0 {
		fmt.Fprintf(&b, "add set inet %s %s { type ipv6_addr; flags interval; }\n", tableName, dohBlockV6Set)
	}

	// 写入集合元素
	writeElements(&b, allowV4Set, allowV4)
	writeElements(&b, denyV4Set, denyV4)
	writeElements(&b, allowV6Set, allowV6)
	writeElements(&b, denyV6Set, denyV6)
	writeElements(&b, dohBlockV4Set, opts.DoHBlocklistV4)
	writeElements(&b, dohBlockV6Set, opts.DoHBlocklistV6)

	// 创建链并设置默认策略
	chainPolicy := "drop"
	if p.DefaultAction == policy.ActionAllow {
		chainPolicy = "accept"
	}
	fmt.Fprintf(&b, "add chain inet %s %s { type filter hook output priority 0; policy %s; }\n", tableName, chainName, chainPolicy)

	// 添加规则
	// 1. 允许已建立的连接
	fmt.Fprintf(&b, "add rule inet %s %s ct state established,related accept\n", tableName, chainName)
	// 2. 允许标记的数据包（代理自身发出的 DNS 查询）
	fmt.Fprintf(&b, "add rule inet %s %s meta mark %s accept\n", tableName, chainName, constants.MarkHex)
	// 3. 允许回环接口
	fmt.Fprintf(&b, "add rule inet %s %s oifname \"lo\" accept\n", tableName, chainName)

	// 4. 阻止 DoT（如启用）
	if opts.BlockDoT {
		fmt.Fprintf(&b, "add rule inet %s %s tcp dport 853 drop\n", tableName, chainName)
		fmt.Fprintf(&b, "add rule inet %s %s udp dport 853 drop\n", tableName, chainName)
	}

	// 5. 阻止 DoH（如启用）
	if opts.BlockDoH443 {
		if len(opts.DoHBlocklistV4) == 0 && len(opts.DoHBlocklistV6) == 0 {
			// 严格模式：启用但无 blocklist 时阻止所有 443
			fmt.Fprintf(&b, "add rule inet %s %s tcp dport 443 drop\n", tableName, chainName)
		} else {
			if len(opts.DoHBlocklistV4) > 0 {
				fmt.Fprintf(&b, "add rule inet %s %s ip daddr @%s tcp dport 443 drop\n", tableName, chainName, dohBlockV4Set)
			}
			if len(opts.DoHBlocklistV6) > 0 {
				fmt.Fprintf(&b, "add rule inet %s %s ip6 daddr @%s tcp dport 443 drop\n", tableName, chainName, dohBlockV6Set)
			}
		}
	}

	// 6. 拒绝规则（针对静态拒绝集合）
	fmt.Fprintf(&b, "add rule inet %s %s ip daddr @%s drop\n", tableName, chainName, denyV4Set)
	fmt.Fprintf(&b, "add rule inet %s %s ip6 daddr @%s drop\n", tableName, chainName, denyV6Set)

	// 7. 允许动态解析的 IP
	fmt.Fprintf(&b, "add rule inet %s %s ip daddr @%s accept\n", tableName, chainName, dynAllowV4Set)
	fmt.Fprintf(&b, "add rule inet %s %s ip6 daddr @%s accept\n", tableName, chainName, dynAllowV6Set)

	// 8. 允许静态 IP
	fmt.Fprintf(&b, "add rule inet %s %s ip daddr @%s accept\n", tableName, chainName, allowV4Set)
	fmt.Fprintf(&b, "add rule inet %s %s ip6 daddr @%s accept\n", tableName, chainName, allowV6Set)

	// 9. 默认拒绝计数器（仅在默认策略为 drop 时）
	if chainPolicy == "drop" {
		fmt.Fprintf(&b, "add rule inet %s %s counter drop\n", tableName, chainName)
	}

	return b.String()
}

// writeElements 写入集合元素到脚本。
func writeElements(b *strings.Builder, setName string, elems []string) {
	if len(elems) == 0 {
		return
	}
	fmt.Fprintf(b, "add element inet %s %s { %s }\n", tableName, setName, strings.Join(elems, ", "))
}

// defaultRunner 默认的 nft 命令执行器。
func defaultRunner(ctx context.Context, script string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, "nft", "-f", "-")
	cmd.Stdin = strings.NewReader(script)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return output, fmt.Errorf("nft apply failed: %w (output: %s)", err, strings.TrimSpace(string(output)))
	}
	return output, nil
}

// isMissingTableError 检查错误是否因为表不存在。
func isMissingTableError(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "no such file or directory") && strings.Contains(msg, "delete table inet "+tableName)
}

// removeDeleteTableLine 移除脚本中的 delete table 行。
func removeDeleteTableLine(script string) string {
	lines := strings.Split(script, "\n")
	var filtered []string
	for _, l := range lines {
		if strings.HasPrefix(l, "delete table inet "+tableName) {
			continue
		}
		if strings.TrimSpace(l) == "" {
			continue
		}
		filtered = append(filtered, l)
	}
	return strings.Join(filtered, "\n")
}
