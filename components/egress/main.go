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

// Egress 组件主入口。
//
// Egress 组件是 OpenSandbox 沙盒的出口流量控制模块，提供以下功能：
// 1. DNS 代理：拦截 DNS 请求，根据策略允许或拒绝域名解析
// 2. nftables 过滤：在 L3/L4 层面控制出站流量（可选 dns+nft 模式）
// 3. 动态策略：通过 HTTP API 动态更新网络策略
// 4. 事件通知：当请求被拒绝时，可通过 webhook 通知外部系统
//
// 运行模式：
// - dns: 仅 DNS 层面的策略控制
// - dns+nft: DNS + nftables 双重控制，提供更细粒度的流量管理
//
// 主要启动流程：
// 1. 解析环境变量中的初始策略
// 2. 创建 DNS 代理并启动
// 3. 配置 iptables 将 DNS 流量重定向到代理
// 4. （可选）配置 nftables 静态策略
// 5. 启动 HTTP 策略服务器
package main

import (
	"context"
	"net/netip"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/alibaba/opensandbox/egress/pkg/constants"
	"github.com/alibaba/opensandbox/egress/pkg/dnsproxy"
	"github.com/alibaba/opensandbox/egress/pkg/events"
	"github.com/alibaba/opensandbox/egress/pkg/iptables"
	"github.com/alibaba/opensandbox/egress/pkg/log"
	slogger "github.com/alibaba/opensandbox/internal/logger"
	"github.com/alibaba/opensandbox/internal/version"
)

func main() {
	// 输出版本信息
	version.EchoVersion("OpenSandbox Egress")

	// 创建可被信号中断的上下文
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	// 初始化日志记录器
	ctx = withLogger(ctx)
	defer log.Logger.Sync()

	// 从环境变量加载初始策略
	initialRules, err := dnsproxy.LoadPolicyFromEnvVar(constants.EnvEgressRules)
	if err != nil {
		log.Fatalf("failed to parse %s: %v", constants.EnvEgressRules, err)
	}

	// 从 /etc/resolv.conf 解析 nameserver IP，用于 nftables 白名单
	allowIPs := AllowIPsForNft("/etc/resolv.conf")
	// 将 nameserver exempt 列表中的 IP 合并到 nftables 允许集合中
	// 这样代理发起到这些目标的流量不会被重定向（不需要设置 SO_MARK）
	for _, addr := range dnsproxy.ParseNameserverExemptList() {
		if !containsAddr(allowIPs, addr) {
			allowIPs = append(allowIPs, addr)
		}
	}

	// 解析运行模式（dns 或 dns+nft）
	mode := parseMode()
	log.Infof("enforcement mode: %s", mode)

	// 创建 nftables 管理器（仅在 dns+nft 模式下）
	nftMgr := createNftManager(mode)

	// 创建并启动 DNS 代理
	proxy, err := dnsproxy.New(initialRules, "")
	if err != nil {
		log.Fatalf("failed to init dns proxy: %v", err)
	}
	if err := proxy.Start(ctx); err != nil {
		log.Fatalf("failed to start dns proxy: %v", err)
	}
	log.Infof("dns proxy started on 127.0.0.1:15353")

	// 配置被拒绝域名的 webhook 通知
	if blockWebhookURL := strings.TrimSpace(os.Getenv(constants.EnvBlockedWebhook)); blockWebhookURL != "" {
		blockedBroadcaster := events.NewBroadcaster(ctx, events.BroadcasterConfig{QueueSize: 256})
		blockedBroadcaster.AddSubscriber(events.NewWebhookSubscriber(blockWebhookURL))
		proxy.SetBlockedBroadcaster(blockedBroadcaster)
		defer blockedBroadcaster.Close()
		log.Infof("denied hostname webhook enabled")
	}

	// 配置 nameserver exempt 列表（代理发起到这些目标的流量不设置 SO_MARK）
	exemptDst := dnsproxy.ParseNameserverExemptList()
	if len(exemptDst) > 0 {
		log.Infof("nameserver exempt list: %v (proxy upstream in this list will not set SO_MARK)", exemptDst)
	}

	// 配置 iptables 规则，将 DNS 流量重定向到本地代理端口
	if err := iptables.SetupRedirect(15353, exemptDst); err != nil {
		log.Fatalf("failed to install iptables redirect: %v", err)
	}
	log.Infof("iptables redirect configured (OUTPUT 53 -> 15353) with SO_MARK bypass for proxy upstream traffic")

	// 配置 nftables（仅在 dns+nft 模式下）
	setupNft(ctx, nftMgr, initialRules, proxy, allowIPs)

	// 启动 HTTP 策略服务器
	httpAddr := envOrDefault(constants.EnvEgressHTTPAddr, constants.DefaultEgressServerAddr)
	if err = startPolicyServer(ctx, proxy, nftMgr, mode, httpAddr, os.Getenv(constants.EnvEgressToken), allowIPs); err != nil {
		log.Fatalf("failed to start policy server: %v", err)
	}
	log.Infof("policy server listening on %s (POST /policy)", httpAddr)

	// 等待退出信号
	<-ctx.Done()
	log.Infof("received shutdown signal; exiting")
	_ = os.Stderr.Sync()
}

// withLogger 创建并配置日志记录器，将其存入上下文。
//
// 参数：
//   ctx: 原始上下文
//
// 返回：
//   包含日志记录器的新上下文
func withLogger(ctx context.Context) context.Context {
	// 从环境变量读取日志级别，默认为 "info"
	level := envOrDefault(constants.EnvEgressLogLevel, "info")
	logger := slogger.MustNew(slogger.Config{Level: level}).Named("opensandbox.egress")
	return log.WithLogger(ctx, logger)
}

// envOrDefault 获取环境变量值，如果为空则返回默认值。
//
// 参数：
//   key: 环境变量名称
//   defaultVal: 默认值
//
// 返回：
//   环境变量值或默认值
func envOrDefault(key, defaultVal string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return defaultVal
}

// isTruthy 检查字符串值是否为真值。
//
// 支持的真值：1, true, yes, y, on（不区分大小写）
//
// 参数：
//   v: 要检查的字符串
//
// 返回：
//   如果是真值返回 true，否则返回 false
func isTruthy(v string) bool {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "1", "true", "yes", "y", "on":
		return true
	default:
		return false
	}
}

// containsAddr 检查地址列表中是否包含指定地址。
//
// 参数：
//   addrs: 地址列表
//   a: 要查找的地址
//
// 返回：
//   如果列表包含该地址返回 true，否则返回 false
func containsAddr(addrs []netip.Addr, a netip.Addr) bool {
	for _, x := range addrs {
		if x == a {
			return true
		}
	}
	return false
}

// parseMode 解析运行模式环境变量。
//
// 支持的模式：
// - "dns" 或 空值：仅 DNS 模式
// - "dns+nft"：DNS + nftables 双重控制模式
// - 其他值：记录警告并回退到 dns 模式
//
// 返回：
//   解析后的运行模式字符串
func parseMode() string {
	mode := strings.ToLower(strings.TrimSpace(os.Getenv(constants.EnvEgressMode)))
	switch mode {
	case "", constants.PolicyDnsOnly:
		return constants.PolicyDnsOnly
	case constants.PolicyDnsNft:
		return constants.PolicyDnsNft
	default:
		log.Warnf("invalid %s=%s, falling back to dns", constants.EnvEgressMode, mode)
		return constants.PolicyDnsOnly
	}
}
