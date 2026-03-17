// Copyright 2025 Alibaba Group Holding Ltd.
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

package model

import "time"

// Metrics 表示系统资源使用指标
//
// Metrics 封装了服务器的系统资源使用情况，包括 CPU 和内存使用率。
// 这些数据用于监控服务器的健康状态和性能。
type Metrics struct {
	// CpuCount CPU 核心数
	CpuCount float64 `json:"cpu_count"`

	// CpuUsedPct CPU 使用率百分比（0-100）
	CpuUsedPct float64 `json:"cpu_used_pct"`

	// MemTotalMiB 总内存大小（MiB）
	MemTotalMiB float64 `json:"mem_total_mib"`

	// MemUsedMiB 已使用内存大小（MiB）
	MemUsedMiB float64 `json:"mem_used_mib"`

	// Timestamp 指标采集时间戳（毫秒）
	Timestamp int64 `json:"timestamp"`
}

// NewMetrics 创建新的指标实例
//
// 本函数初始化一个 Metrics 对象，所有数值字段初始化为 0，
// 时间戳设置为当前时间。
//
// 返回值:
//   - *Metrics: 新的指标实例
func NewMetrics() *Metrics {
	return &Metrics{
		CpuCount:    0,
		CpuUsedPct:  0,
		MemTotalMiB: 0,
		MemUsedMiB:  0,
		Timestamp:   time.Now().UnixMilli(),
	}
}
