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

// 常量定义包 - 配置相关。
//
// 本文件定义了 Egress 组件使用的环境变量名称和默认值。
package constants

const (
	// OPENSANDBOX_EGRESS_BLOCK_DOH_443: 是否阻止 DoH (DNS over HTTPS) 443 端口
	EnvBlockDoH443 = "OPENSANDBOX_EGRESS_BLOCK_DOH_443"

	// OPENSANDBOX_EGRESS_DOH_BLOCKLIST: DoH 阻止列表（逗号分隔的 IP/CIDR）
	EnvDoHBlocklist = "OPENSANDBOX_EGRESS_DOH_BLOCKLIST"

	// OPENSANDBOX_EGRESS_MODE: 运行模式（dns | dns+nft）
	EnvEgressMode = "OPENSANDBOX_EGRESS_MODE"

	// OPENSANDBOX_EGRESS_HTTP_ADDR: HTTP 策略服务器监听地址
	EnvEgressHTTPAddr = "OPENSANDBOX_EGRESS_HTTP_ADDR"

	// OPENSANDBOX_EGRESS_TOKEN: HTTP 策略服务器认证令牌
	EnvEgressToken = "OPENSANDBOX_EGRESS_TOKEN"

	// OPENSANDBOX_EGRESS_RULES: 初始网络策略（JSON 格式）
	EnvEgressRules = "OPENSANDBOX_EGRESS_RULES"

	// OPENSANDBOX_EGRESS_LOG_LEVEL: 日志级别（debug, info, warn, error）
	EnvEgressLogLevel = "OPENSANDBOX_EGRESS_LOG_LEVEL"

	// OPENSANDBOX_EGRESS_MAX_NS: nameserver 数量限制
	EnvMaxNameservers = "OPENSANDBOX_EGRESS_MAX_NS"

	// OPENSANDBOX_EGRESS_DENY_WEBHOOK: 被拒绝域名的 webhook 通知 URL
	EnvBlockedWebhook = "OPENSANDBOX_EGRESS_DENY_WEBHOOK"

	// OPENSANDBOX_EGRESS_SANDBOX_ID: 沙盒 ID
	ENVSandboxID = "OPENSANDBOX_EGRESS_SANDBOX_ID"

	// OPENSANDBOX_EGRESS_NAMESERVER_EXEMPT: 逗号分隔的 IP 列表；
	// 代理发起到这些目标的流量不会被设置 SO_MARK，会遵循正常路由（如通过 tun）
	EnvNameserverExempt = "OPENSANDBOX_EGRESS_NAMESERVER_EXEMPT"
)

const (
	// PolicyDnsOnly: 仅 DNS 策略模式
	PolicyDnsOnly = "dns"

	// PolicyDnsNft: DNS + nftables 双重控制模式
	PolicyDnsNft = "dns+nft"
)

const (
	// DefaultEgressServerAddr: HTTP 策略服务器默认监听地址
	DefaultEgressServerAddr = ":18080"

	// DefaultMaxNameservers: 默认 nameserver 数量限制
	DefaultMaxNameservers = 3
)
