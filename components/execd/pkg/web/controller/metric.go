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

package controller

import (
	"encoding/json"
	"fmt"
	"net/http"
	"runtime"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/shirou/gopsutil/cpu"
	"github.com/shirou/gopsutil/mem"

	"github.com/alibaba/opensandbox/execd/pkg/log"
	"github.com/alibaba/opensandbox/execd/pkg/web/model"
)

// MetricController 系统指标控制器
//
// MetricController 处理系统资源指标的请求，
// 提供 CPU 和内存使用情况的查询和监控功能。
type MetricController struct {
	// basicController 基础控制器嵌入
	*basicController
}

// NewMetricController 创建指标控制器实例
//
// 参数:
//   - ctx: Gin 上下文
//
// 返回值:
//   - *MetricController: 新创建的控制器实例
func NewMetricController(ctx *gin.Context) *MetricController {
	return &MetricController{basicController: newBasicController(ctx)}
}

// GetMetrics 获取当前系统指标
//
// 本接口返回当前的 CPU 和内存使用指标。
func (c *MetricController) GetMetrics() {
	metrics, err := c.readMetrics()
	if err != nil {
		c.RespondError(
			http.StatusInternalServerError,
			model.ErrorCodeRuntimeError,
			fmt.Sprintf("error reading runtime metrics. %v", err),
		)
		return
	}

	c.RespondSuccess(metrics)
}

// WatchMetrics 通过 SSE 流式推送系统指标
//
// 本接口建立 SSE 连接，每秒推送一次系统指标。
// 客户端断开连接时自动停止推送。
func (c *MetricController) WatchMetrics() {
	c.setupSSEResponse()

	for {
		select {
		case <-c.ctx.Request.Context().Done():
			// 客户端断开连接
			return
		case <-time.After(time.Second * 1):
			func() {
				if flusher, ok := c.ctx.Writer.(http.Flusher); ok {
					defer flusher.Flush()
				}
				metrics, err := c.readMetrics()
				if err != nil {
					msg, _ := json.Marshal(map[string]string{ //nolint:errchkjson
						"error": err.Error(),
					})
					_, err = c.ctx.Writer.Write(append(msg, '\n'))
					if err != nil {
						log.Error("WatchMetrics write data %s error: %v", string(msg), err)
					}
				} else {
					msg, _ := json.Marshal(metrics) //nolint:errchkjson
					_, err = c.ctx.Writer.Write(append(msg, '\n'))
					if err != nil {
						log.Error("WatchMetrics write data %s error: %v", string(msg), err)
					}
				}
			}()
		}
	}
}

// readMetrics 收集当前 CPU 和内存指标
//
// 本函数读取系统 CPU 使用率和内存使用情况。
//
// 返回值:
//   - *model.Metrics: 指标数据
//   - error: 读取错误（如有）
func (c *MetricController) readMetrics() (*model.Metrics, error) {
	metric := model.NewMetrics()

	// 获取 CPU 核心数
	metric.CpuCount = float64(runtime.GOMAXPROCS(-1))

	// 获取 CPU 使用率
	cpuPercent, err := cpu.Percent(time.Second, false)
	if err != nil {
		return nil, fmt.Errorf("failed to get CPU percent: %w", err)
	}
	if len(cpuPercent) > 0 {
		metric.CpuUsedPct = cpuPercent[0]
	}

	// 获取内存使用情况
	vmStat, err := mem.VirtualMemory()
	if err != nil {
		return nil, fmt.Errorf("failed to get memory info: %w", err)
	}
	metric.MemTotalMiB = float64(vmStat.Total) / 1024 / 1024
	metric.MemUsedMiB = float64(vmStat.Used) / 1024 / 1024

	return metric, nil
}
