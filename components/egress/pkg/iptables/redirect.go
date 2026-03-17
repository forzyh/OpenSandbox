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

// iptables 规则配置。
//
// 本文件实现 iptables 规则配置，用于将 DNS 流量重定向到本地代理。
package iptables

import (
	"fmt"
	"net/netip"
	"os/exec"
	"strconv"

	"github.com/alibaba/opensandbox/egress/pkg/constants"
	"github.com/alibaba/opensandbox/egress/pkg/log"
)

// SetupRedirect 配置 iptables DNS 重定向规则。
//
// 该函数安装以下规则：
// 1. 为每个 exempt 目标 IP 添加 RETURN 规则（IPv4 和 IPv6）
// 2. 为标记的数据包添加 RETURN 规则（代理自身发出的 DNS 查询）
// 3. 将所有其他 DNS 流量重定向到本地代理端口
//
// 需要 CAP_NET_ADMIN 能力。
//
// 参数：
//   port: 重定向目标端口（代理监听端口）
//   exemptDst: 豁免的目标 IP 列表；发往这些 IP 的流量不会被重定向
//
// 返回：
//   配置错误（如有）
func SetupRedirect(port int, exemptDst []netip.Addr) error {
	log.Infof("installing iptables DNS redirect: OUTPUT port 53 -> %d (mark %s bypass)", port, constants.MarkHex)
	targetPort := strconv.Itoa(port)

	var rules [][]string

	// 为每个 exempt 目标添加 RETURN 规则
	for _, d := range exemptDst {
		addr := d
		dStr := d.String()
		if addr.Is4() {
			rules = append(rules,
				[]string{"iptables", "-t", "nat", "-A", "OUTPUT", "-p", "udp", "--dport", "53", "-d", dStr, "-j", "RETURN"},
				[]string{"iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "--dport", "53", "-d", dStr, "-j", "RETURN"},
			)
		} else {
			rules = append(rules,
				[]string{"ip6tables", "-t", "nat", "-A", "OUTPUT", "-p", "udp", "--dport", "53", "-d", dStr, "-j", "RETURN"},
				[]string{"ip6tables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "--dport", "53", "-d", dStr, "-j", "RETURN"},
			)
		}
	}

	// 标记并重定向规则
	markAndRedirect := [][]string{
		// IPv4: 标记的数据包 RETURN（代理自身发出的 DNS 查询）
		{"iptables", "-t", "nat", "-A", "OUTPUT", "-p", "udp", "--dport", "53", "-m", "mark", "--mark", constants.MarkHex, "-j", "RETURN"},
		{"iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "--dport", "53", "-m", "mark", "--mark", constants.MarkHex, "-j", "RETURN"},
		// IPv4: 重定向其他 DNS 流量到代理
		{"iptables", "-t", "nat", "-A", "OUTPUT", "-p", "udp", "--dport", "53", "-j", "REDIRECT", "--to-port", targetPort},
		{"iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "--dport", "53", "-j", "REDIRECT", "--to-port", targetPort},
		// IPv6: 标记的数据包 RETURN
		{"ip6tables", "-t", "nat", "-A", "OUTPUT", "-p", "udp", "--dport", "53", "-m", "mark", "--mark", constants.MarkHex, "-j", "RETURN"},
		{"ip6tables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "--dport", "53", "-m", "mark", "--mark", constants.MarkHex, "-j", "RETURN"},
		// IPv6: 重定向其他 DNS 流量到代理
		{"ip6tables", "-t", "nat", "-A", "OUTPUT", "-p", "udp", "--dport", "53", "-j", "REDIRECT", "--to-port", targetPort},
		{"ip6tables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "--dport", "53", "-j", "REDIRECT", "--to-port", targetPort},
	}
	rules = append(rules, markAndRedirect...)

	// 执行所有 iptables 命令
	for _, args := range rules {
		if output, err := exec.Command(args[0], args[1:]...).CombinedOutput(); err != nil {
			return fmt.Errorf("iptables command failed: %v (output: %s)", err, output)
		}
	}
	log.Infof("iptables DNS redirect installed successfully")
	return nil
}
