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

//go:build !linux

// 非 Linux 平台的 DNS 代理实现。
//
// 非 Linux 平台不支持 SO_MARK，返回基本拨号器。
package dnsproxy

import (
	"net"
	"time"
)

// dialerWithMark 非 Linux 平台：无 SO_MARK，返回基本拨号器。
func (p *Proxy) dialerWithMark() *net.Dialer {
	return &net.Dialer{Timeout: 5 * time.Second}
}
