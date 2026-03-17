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
	"context"
	"io"
	"net/http"
	"time"

	"k8s.io/apimachinery/pkg/util/wait"

	"github.com/alibaba/opensandbox/execd/pkg/jupyter/execute"
	"github.com/alibaba/opensandbox/execd/pkg/log"
	"github.com/alibaba/opensandbox/execd/pkg/runtime"
	"github.com/alibaba/opensandbox/execd/pkg/util/safego"
	"github.com/alibaba/opensandbox/execd/pkg/web/model"
)

// sseHeaders SSE 响应头配置
//
// 这些响应头用于配置 SSE（Server-Sent Events）连接：
//   - Content-Type: 指定为事件流格式
//   - Cache-Control: 禁用缓存，确保实时接收事件
//   - Connection: 保持长连接
//   - X-Accel-Buffering: 禁用 Nginx 缓冲
var sseHeaders = map[string]string{
	"Content-Type":      "text/event-stream",
	"Cache-Control":     "no-cache",
	"Connection":        "keep-alive",
	"X-Accel-Buffering": "no",
}

// setupSSEResponse 设置 SSE 响应头
//
// 本方法配置 SSE 所需的响应头，并立即刷新响应，
// 确保客户端可以立即开始接收事件。
func (c *basicController) setupSSEResponse() {
	for key, value := range sseHeaders {
		c.ctx.Writer.Header().Set(key, value)
	}
	if flusher, ok := c.ctx.Writer.(http.Flusher); ok {
		flusher.Flush()
	}
}

// setServerEventsHandler 设置服务器事件处理器
//
// 本方法将 runtime 的回调函数适配为 SSE 事件，
// 使执行过程中的各种状态可以通过 SSE 推送给客户端。
//
// 参数:
//   - ctx: 执行上下文
//
// 返回值:
//   - runtime.ExecuteResultHook: 配置好的回调函数集合
func (c *CodeInterpretingController) setServerEventsHandler(ctx context.Context) runtime.ExecuteResultHook {
	return runtime.ExecuteResultHook{
		// 执行初始化回调
		OnExecuteInit: func(session string) {
			event := model.ServerStreamEvent{
				Type:      model.StreamEventTypeInit,
				Text:      session,
				Timestamp: time.Now().UnixMilli(),
			}
			payload := event.ToJSON()
			c.writeSingleEvent("OnExecuteInit", payload, true, event.Summary())

			// 启动后台 ping 协程保持连接活跃
			safego.Go(func() { c.ping(ctx) })
		},

		// 执行结果回调
		OnExecuteResult: func(result map[string]any, count int) {
			var mutated map[string]any
			if len(result) > 0 {
				mutated = make(map[string]any)
				for k, v := range result {
					switch k {
					case "text/plain":
						// 将 text/plain 重命名为 text 便于客户端处理
						mutated["text"] = v
					default:
						mutated[k] = v
					}
				}
			}

			// 发送执行计数事件
			if count > 0 {
				event := model.ServerStreamEvent{
					Type:           model.StreamEventTypeCount,
					ExecutionCount: count,
					Timestamp:      time.Now().UnixMilli(),
				}
				payload := event.ToJSON()
				c.writeSingleEvent("OnExecuteResult", payload, true, event.Summary())
			}

			// 发送执行结果事件
			if len(mutated) > 0 {
				event := model.ServerStreamEvent{
					Type:      model.StreamEventTypeResult,
					Results:   mutated,
					Timestamp: time.Now().UnixMilli(),
				}
				payload := event.ToJSON()
				c.writeSingleEvent("OnExecuteResult", payload, true, event.Summary())
			}
		},

		// 执行完成回调
		OnExecuteComplete: func(executionTime time.Duration) {
			event := model.ServerStreamEvent{
				Type:          model.StreamEventTypeComplete,
				ExecutionTime: executionTime.Milliseconds(),
				Timestamp:     time.Now().UnixMilli(),
			}
			payload := event.ToJSON()
			c.writeSingleEvent("OnExecuteComplete", payload, true, event.Summary())
		},

		// 执行错误回调
		OnExecuteError: func(err *execute.ErrorOutput) {
			if err == nil {
				return
			}

			event := model.ServerStreamEvent{
				Type:      model.StreamEventTypeError,
				Error:     err,
				Timestamp: time.Now().UnixMilli(),
			}
			payload := event.ToJSON()
			c.writeSingleEvent("OnExecuteError", payload, true, event.Summary())
		},

		// 状态更新回调
		OnExecuteStatus: func(status string) {
			event := model.ServerStreamEvent{
				Type:      model.StreamEventTypeStatus,
				Text:      status,
				Timestamp: time.Now().UnixMilli(),
			}
			payload := event.ToJSON()
			c.writeSingleEvent("OnExecuteStatus", payload, true, event.Summary())
		},

		// 标准输出回调
		OnExecuteStdout: func(text string) {
			if text == "" {
				return
			}

			event := model.ServerStreamEvent{
				Type:      model.StreamEventTypeStdout,
				Text:      text,
				Timestamp: time.Now().UnixMilli(),
			}
			payload := event.ToJSON()
			c.writeSingleEvent("OnExecuteStdout", payload, true, event.Summary())
		},

		// 标准错误回调
		OnExecuteStderr: func(text string) {
			if text == "" {
				return
			}

			event := model.ServerStreamEvent{
				Type:      model.StreamEventTypeStderr,
				Text:      text,
				Timestamp: time.Now().UnixMilli(),
			}
			payload := event.ToJSON()
			c.writeSingleEvent("OnExecuteStderr", payload, true, event.Summary())
		},
	}
}

// writeSingleEvent 写入单个 SSE 事件
//
// 本方法将事件数据序列化并通过 SSE 连接发送给客户端。
//
// 参数:
//   - handler: 处理器名称（用于日志）
//   - data: 事件数据（JSON 格式）
//   - verbose: 是否记录详细日志
//   - summary: 事件摘要（用于日志）
func (c *CodeInterpretingController) writeSingleEvent(handler string, data []byte, verbose bool, summary string) {
	if c == nil || c.ctx == nil || c.ctx.Writer == nil {
		return
	}

	// 检查客户端是否已断开连接
	select {
	case <-c.ctx.Request.Context().Done():
		log.Error("StreamEvent.%s: client disconnected", handler)
		return
	default:
	}

	c.chunkWriter.Lock()
	defer c.chunkWriter.Unlock()
	defer func() {
		if flusher, ok := c.ctx.Writer.(http.Flusher); ok {
			flusher.Flush()
		}
	}()

	// SSE 格式：数据后跟两个换行符
	payload := append(data, '\n', '\n')
	n, err := c.ctx.Writer.Write(payload)
	if err == nil && n != len(payload) {
		err = io.ErrShortWrite
	}

	if err != nil {
		log.Error("StreamEvent.%s write data %s error: %v", handler, summary, err)
	} else {
		if verbose {
			log.Info("StreamEvent.%s write data %s", handler, summary)
		}
	}
}

// ping 定期发送 ping 事件保持 SSE 连接活跃
//
// 本方法每 3 秒发送一次 ping 事件，防止中间设备（如 Nginx、负载均衡器）
// 因连接空闲而关闭连接。
//
// 参数:
//   - ctx: 执行上下文，用于控制 goroutine 退出
func (c *CodeInterpretingController) ping(ctx context.Context) {
	wait.Until(func() {
		if c.ctx.Writer == nil {
			return
		}
		event := model.ServerStreamEvent{
			Type:      model.StreamEventTypePing,
			Text:      "pong",
			Timestamp: time.Now().UnixMilli(),
		}
		payload := event.ToJSON()
		c.writeSingleEvent("Ping", payload, false, event.Summary())
	}, 3*time.Second, ctx.Done())
}
