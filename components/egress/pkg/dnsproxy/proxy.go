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

// DNS 代理实现。
//
// 本文件实现了 DNS 代理的核心功能：
// 1. 监听本地 DNS 请求（默认 127.0.0.1:15353）
// 2. 根据网络策略允许或拒绝域名解析
// 3. 转发允许的请求到上游 DNS 服务器
// 4. 通知 DNS 解析结果（用于动态 nftables 规则）
// 5. 通知被拒绝的域名（用于 webhook 通知）
package dnsproxy

import (
	"context"
	"fmt"
	"net"
	"net/netip"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/miekg/dns"

	"github.com/alibaba/opensandbox/egress/pkg/events"
	"github.com/alibaba/opensandbox/egress/pkg/log"
	"github.com/alibaba/opensandbox/egress/pkg/nftables"
	"github.com/alibaba/opensandbox/egress/pkg/policy"
)

// 默认监听地址
const defaultListenAddr = "127.0.0.1:15353"

// Proxy DNS 代理结构体。
type Proxy struct {
	policyMu   sync.RWMutex    // 保护策略的读写锁
	policy     *policy.NetworkPolicy // 当前网络策略
	listenAddr string          // 监听地址
	upstream   string          // 上游 DNS 服务器地址
	servers    []*dns.Server   // DNS 服务器实例（UDP 和 TCP）

	// 可选回调；当 A/AAAA 记录存在时在 goroutine 中调用
	onResolved func(domain string, ips []nftables.ResolvedIP)

	// 可选的事件广播器，用于通知被拒绝的域名
	blockedBroadcaster *events.Broadcaster
}

// New 创建 DNS 代理实例。
//
// 参数：
//   p: 初始网络策略（nil 使用默认拒绝所有）
//   listenAddr: 监听地址（空字符串使用默认地址）
//
// 返回：
//   DNS 代理实例和可能的错误
func New(p *policy.NetworkPolicy, listenAddr string) (*Proxy, error) {
	if listenAddr == "" {
		listenAddr = defaultListenAddr
	}
	if p == nil {
		p = policy.DefaultDenyPolicy()
	}

	// 自动发现上游 DNS 服务器
	upstream, err := discoverUpstream()
	if err != nil {
		return nil, err
	}

	proxy := &Proxy{
		listenAddr: listenAddr,
		upstream:   upstream,
		policy:     ensurePolicyDefaults(p),
	}
	return proxy, nil
}

// Start 启动 DNS 代理服务器。
//
// 参数：
//   ctx: 上下文，用于优雅关闭
//
// 返回：
//   启动错误（如有）
func (p *Proxy) Start(ctx context.Context) error {
	handler := dns.HandlerFunc(p.serveDNS)

	// 创建 UDP 和 TCP DNS 服务器
	udpServer := &dns.Server{Addr: p.listenAddr, Net: "udp", Handler: handler}
	tcpServer := &dns.Server{Addr: p.listenAddr, Net: "tcp", Handler: handler}
	p.servers = []*dns.Server{udpServer, tcpServer}

	// 在后台启动服务器
	errCh := make(chan error, len(p.servers))
	for _, srv := range p.servers {
		s := srv
		go func() {
			if err := s.ListenAndServe(); err != nil {
				errCh <- err
			}
		}()
	}

	// 上下文结束时关闭服务器
	go func() {
		<-ctx.Done()
		for _, srv := range p.servers {
			_ = srv.Shutdown()
		}
	}()

	// 等待启动完成或错误
	select {
	case err := <-errCh:
		return fmt.Errorf("dns proxy failed: %w", err)
	case <-time.After(200 * time.Millisecond):
		// 小延迟确认启动成功
		return nil
	}
}

// serveDNS 处理 DNS 请求。
//
// 处理流程：
// 1. 检查域名是否被策略拒绝
// 2. 如果拒绝，返回 NXDOMAIN
// 3. 如果允许，转发到上游 DNS 服务器
// 4. 通知 DNS 解析结果（如有回调）
func (p *Proxy) serveDNS(w dns.ResponseWriter, r *dns.Msg) {
	if len(r.Question) == 0 {
		_ = w.WriteMsg(new(dns.Msg)) // 空响应
		return
	}
	q := r.Question[0]
	domain := q.Name

	// 获取当前策略
	p.policyMu.RLock()
	currentPolicy := p.policy
	p.policyMu.RUnlock()

	// 评估域名是否被拒绝
	if currentPolicy != nil && currentPolicy.Evaluate(domain) == policy.ActionDeny {
		p.publishBlocked(domain)
		resp := new(dns.Msg)
		resp.SetRcode(r, dns.RcodeNameError)
		_ = w.WriteMsg(resp)
		return
	}

	// 转发到上游 DNS 服务器
	resp, err := p.forward(r)
	if err != nil {
		log.Warnf("[dns] forward error for %s: %v", domain, err)
		fail := new(dns.Msg)
		fail.SetRcode(r, dns.RcodeServerFailure)
		_ = w.WriteMsg(fail)
		return
	}

	// 通知 DNS 解析结果
	p.maybeNotifyResolved(domain, resp)
	_ = w.WriteMsg(resp)
}

// maybeNotifyResolved 在响应包含 A/AAAA 记录时调用 onResolved 回调。
//
// 这样在客户端收到 DNS 响应并建立连接之前，
// IP 已经被添加到 nftables 允许集合中。
func (p *Proxy) maybeNotifyResolved(domain string, resp *dns.Msg) {
	if p.onResolved == nil {
		return
	}
	ips := extractResolvedIPs(resp)
	if len(ips) == 0 {
		return
	}
	p.onResolved(domain, ips)
}

// forward 将 DNS 请求转发到上游服务器。
func (p *Proxy) forward(r *dns.Msg) (*dns.Msg, error) {
	c := &dns.Client{
		Timeout: 5 * time.Second,
		Dialer:  p.dialerWithMark(),
	}
	resp, _, err := c.Exchange(r, p.upstream)
	return resp, err
}

// UpstreamHost 返回上游 DNS 服务器的主机部分。
func (p *Proxy) UpstreamHost() string {
	host, _, err := net.SplitHostPort(p.upstream)
	if err != nil {
		return ""
	}
	return host
}

// UpdatePolicy 更新代理使用的网络策略。
//
// 参数：
//   newPolicy: 新策略（nil 回退到默认拒绝所有）
func (p *Proxy) UpdatePolicy(newPolicy *policy.NetworkPolicy) {
	p.policyMu.Lock()
	p.policy = ensurePolicyDefaults(newPolicy)
	p.policyMu.Unlock()
}

// CurrentPolicy 返回当前生效的网络策略。
func (p *Proxy) CurrentPolicy() *policy.NetworkPolicy {
	p.policyMu.RLock()
	defer p.policyMu.RUnlock()
	return p.policy
}

// SetOnResolved 设置 DNS 解析结果回调。
//
// 当允许的域名解析到 A/AAAA 记录时调用此回调。
// 在 goroutine 中调用；传 nil 禁用。
// 仅在 L2 动态 IP 启用时使用（如 dns+nft 模式）。
func (p *Proxy) SetOnResolved(fn func(domain string, ips []nftables.ResolvedIP)) {
	p.onResolved = fn
}

// SetBlockedBroadcaster 设置被拒绝域名的事件广播器。
func (p *Proxy) SetBlockedBroadcaster(b *events.Broadcaster) {
	p.blockedBroadcaster = b
}

// publishBlocked 发布被拒绝的域名到广播器。
func (p *Proxy) publishBlocked(domain string) {
	if p.blockedBroadcaster == nil {
		return
	}
	normalized := strings.ToLower(strings.TrimSuffix(domain, "."))
	if normalized == "" {
		return
	}

	p.blockedBroadcaster.Publish(events.BlockedEvent{
		Hostname:  normalized,
		Timestamp: time.Now().UTC(),
	})
}

// extractResolvedIPs 从 DNS 响应中提取 A 和 AAAA 记录。
//
// 使用 netip.ParseAddr(v.A.String()) 为每条记录分配临时字符串；
// 通常每条解析只有一到几条记录，成本相比 DNS RTT 和 nft 写入很小。
func extractResolvedIPs(resp *dns.Msg) []nftables.ResolvedIP {
	if resp == nil || len(resp.Answer) == 0 {
		return nil
	}

	var out []nftables.ResolvedIP
	for _, rr := range resp.Answer {
		switch v := rr.(type) {
		case *dns.A:
			if v.A == nil {
				continue
			}
			addr, err := netip.ParseAddr(v.A.String())
			if err != nil {
				continue
			}
			out = append(out, nftables.ResolvedIP{Addr: addr, TTL: time.Duration(v.Hdr.Ttl) * time.Second})
		case *dns.AAAA:
			if v.AAAA == nil {
				continue
			}
			addr, err := netip.ParseAddr(v.AAAA.String())
			if err != nil {
				continue
			}
			out = append(out, nftables.ResolvedIP{Addr: addr, TTL: time.Duration(v.Hdr.Ttl) * time.Second})
		}
	}
	return out
}

// 备用的上游 DNS 服务器（当 /etc/resolv.conf 无法解析时使用）
const fallbackUpstream = "8.8.8.8:53"

// discoverUpstream 自动发现上游 DNS 服务器。
//
// 优先选择第一个非回环 nameserver（如 K8s 集群 DNS 在 127.0.0.11 之后）。
// 如果只有回环地址（如 Docker 127.0.0.11），使用它：代理的上游流量会被标记并绕过重定向，
// 所以回环地址在 sidecar 中是可达的。
func discoverUpstream() (string, error) {
	cfg, err := dns.ClientConfigFromFile("/etc/resolv.conf")
	if err != nil || len(cfg.Servers) == 0 {
		if err != nil {
			log.Warnf("[dns] fallback upstream resolver due to error: %v", err)
		}
		return fallbackUpstream, nil
	}

	// 选择第一个非回环 nameserver
	var chosen string
	for _, s := range cfg.Servers {
		if ip := net.ParseIP(s); ip != nil && ip.IsLoopback() {
			if chosen == "" {
				chosen = s
			}
			continue
		}
		chosen = s
		break
	}
	if chosen == "" {
		chosen = cfg.Servers[0]
	}
	return net.JoinHostPort(chosen, cfg.Port), nil
}

// ResolvNameserverIPs 从 resolv.conf 读取 nameserver 行并返回解析的 IPv4/IPv6 地址。
//
// 用于启动时白名单系统 DNS，确保客户端 DNS 流量被允许且代理可以将其作为上游使用。
//
// 参数：
//   resolvPath: resolv.conf 文件路径
//
// 返回：
//   nameserver IP 列表和可能的错误
func ResolvNameserverIPs(resolvPath string) ([]netip.Addr, error) {
	cfg, err := dns.ClientConfigFromFile(resolvPath)
	if err != nil || len(cfg.Servers) == 0 {
		return nil, nil
	}
	var out []netip.Addr
	for _, s := range cfg.Servers {
		ip, err := netip.ParseAddr(s)
		if err != nil {
			continue
		}
		out = append(out, ip)
	}
	return out, nil
}

// LoadPolicyFromEnvVar 从环境变量读取并解析网络策略。
//
// 参数：
//   envName: 环境变量名称
//
// 返回：
//   解析后的策略和可能的错误
func LoadPolicyFromEnvVar(envName string) (*policy.NetworkPolicy, error) {
	raw := os.Getenv(envName)
	if raw == "" {
		return policy.DefaultDenyPolicy(), nil
	}
	return policy.ParsePolicy(raw)
}

// ensurePolicyDefaults 确保策略有默认值。
func ensurePolicyDefaults(p *policy.NetworkPolicy) *policy.NetworkPolicy {
	if p == nil {
		return policy.DefaultDenyPolicy()
	}
	if p.DefaultAction == "" {
		p.DefaultAction = policy.ActionDeny
	}
	return p
}
