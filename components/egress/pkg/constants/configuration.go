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

// 常量定义包 - 底层配置。
//
// 本文件定义了 Egress 组件使用的底层常量和配置值。
package constants

const (
	// MarkValue: iptables/nftables 使用的 SO_MARK 值
	// 用于标记代理发出的 DNS 查询流量，使其绕过 DNS 重定向
	MarkValue = 0x1

	// MarkHex: Mark 值的十六进制字符串表示
	MarkHex = "0x1"
)

const (
	// EgressAuthTokenHeader: HTTP 策略服务器认证头名称
	EgressAuthTokenHeader = "OPENSANDBOX-EGRESS-AUTH"
)
