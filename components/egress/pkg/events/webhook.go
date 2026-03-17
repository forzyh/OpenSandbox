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

// Webhook 订阅者实现。
//
// 本文件实现了 WebhookSubscriber，用于将被拒绝的域名事件
// 通过 HTTP POST 发送到配置的 webhook 端点。
package events

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/alibaba/opensandbox/egress/pkg/constants"
	"github.com/alibaba/opensandbox/egress/pkg/log"
)

// Webhook 配置常量
const (
	webhookSource         = "opensandbox-egress" // 事件来源标识
	defaultWebhookTimeout = 5 * time.Second      // 默认请求超时
	defaultWebhookRetries = 3                    // 默认重试次数
	defaultWebhookBackoff = 1 * time.Second      // 默认退避时间
)

// WebhookSubscriber 将被拒绝事件发送到 HTTP 端点。
type WebhookSubscriber struct {
	url        string       // webhook URL
	client     *http.Client // HTTP 客户端
	timeout    time.Duration // 请求超时
	maxRetries int          // 最大重试次数
	backoff    time.Duration // 退避时间
	sandboxID  string       // 沙盒 ID（从环境变量获取）
}

// webhookPayload Webhook 请求体结构。
type webhookPayload struct {
	Hostname  string `json:"hostname"`  // 被拒绝的域名
	Timestamp string `json:"timestamp"` // 时间戳（RFC3339 格式）
	Source    string `json:"source"`    // 事件来源
	SandboxID string `json:"sandboxId"` // 沙盒 ID
}

// NewWebhookSubscriber 创建 Webhook 订阅者实例。
//
// 参数：
//   url: webhook URL
//
// 返回：
//   Webhook 订阅者实例（url 为空时返回 nil）
func NewWebhookSubscriber(url string) *WebhookSubscriber {
	if url == "" {
		return nil
	}
	return &WebhookSubscriber{
		url:        url,
		client:     &http.Client{},
		timeout:    defaultWebhookTimeout,
		maxRetries: defaultWebhookRetries,
		backoff:    defaultWebhookBackoff,
		sandboxID:  os.Getenv(constants.ENVSandboxID),
	}
}

// HandleBlocked 发送被拒绝事件到配置的 webhook，带重试。
//
// 重试策略：
// - 最多重试 maxRetries 次
// - 每次重试使用指数退避（backoff * 2^attempt）
// - 4xx 错误不重试（非可重试错误）
// - 5xx 错误和网络错误会重试
//
// 参数：
//   ctx: 上下文
//   ev: 被拒绝事件
func (w *WebhookSubscriber) HandleBlocked(ctx context.Context, ev BlockedEvent) {
	payload := webhookPayload{
		Hostname:  ev.Hostname,
		Timestamp: ev.Timestamp.UTC().Format(time.RFC3339),
		Source:    webhookSource,
		SandboxID: w.sandboxID,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		log.Warnf("[webhook] failed to marshal payload for hostname %s: %v", ev.Hostname, err)
		return
	}

	var lastErr error
	for attempt := 0; attempt <= w.maxRetries; attempt++ {
		reqCtx := ctx
		cancel := func() {}
		if w.timeout > 0 {
			reqCtx, cancel = context.WithTimeout(ctx, w.timeout)
		}

		req, err := http.NewRequestWithContext(reqCtx, http.MethodPost, w.url, bytes.NewReader(body))
		if err != nil {
			cancel()
			lastErr = err
			break
		}
		req.Header.Set("Content-Type", "application/json")

		resp, err := w.client.Do(req)
		if err == nil {
			_, _ = io.Copy(io.Discard, resp.Body)
			_ = resp.Body.Close()
			if resp.StatusCode < 300 {
				// 成功
				cancel()
				return
			}
			if resp.StatusCode < 500 {
				// 4xx 错误，不重试
				cancel()
				log.Warnf("[webhook] non-retriable status %d for hostname %s", resp.StatusCode, payload.Hostname)
				return
			}
			// 5xx 错误，记录错误继续重试
			err = fmt.Errorf("status %d", resp.StatusCode)
		}

		cancel()
		lastErr = err
		if attempt < w.maxRetries {
			// 指数退避
			time.Sleep(w.backoff * time.Duration(1<<attempt))
		}
	}

	if lastErr != nil {
		log.Warnf("[webhook] failed to notify hostname %s after retries: %v", payload.Hostname, lastErr)
	}
}
