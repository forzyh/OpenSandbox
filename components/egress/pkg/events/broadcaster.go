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

// 事件系统实现。
//
// 本文件实现了事件广播器（Broadcaster），用于将被拒绝的域名事件
// 分发给多个订阅者（如 webhook 通知）。
package events

import (
	"context"
	"sync"
	"sync/atomic"
	"time"

	"github.com/alibaba/opensandbox/egress/pkg/log"
)

// 默认队列大小
const defaultQueueSize = 128

// BlockedEvent 描述被拒绝的域名通知事件。
type BlockedEvent struct {
	Hostname  string    `json:"hostname"`  // 被拒绝的域名
	Timestamp time.Time `json:"timestamp"` // 事件时间戳
}

// Subscriber 定义事件订阅者接口。
type Subscriber interface {
	// HandleBlocked 处理被拒绝事件
	HandleBlocked(ctx context.Context, ev BlockedEvent)
}

// BroadcasterConfig 定义广播器队列大小配置。
type BroadcasterConfig struct {
	QueueSize int // 每个订阅者的队列大小
}

// Broadcaster 通过通道将事件分发给多个订阅者。
type Broadcaster struct {
	ctx    context.Context
	cancel context.CancelFunc

	mu          sync.RWMutex
	subscribers []chan BlockedEvent // 订阅者通道列表
	queueSize   int                 // 每个通道的缓冲大小
	closed      atomic.Bool         // 关闭标志
}

// NewBroadcaster 创建广播器实例。
//
// 参数：
//   ctx: 父上下文
//   cfg: 广播器配置
//
// 返回：
//   广播器实例
func NewBroadcaster(ctx context.Context, cfg BroadcasterConfig) *Broadcaster {
	if cfg.QueueSize <= 0 {
		cfg.QueueSize = defaultQueueSize
	}
	cctx, cancel := context.WithCancel(ctx)
	return &Broadcaster{
		ctx:       cctx,
		cancel:    cancel,
		queueSize: cfg.QueueSize,
	}
}

// AddSubscriber 注册新订阅者。
//
// 为每个订阅者创建独立的缓冲通道和 worker goroutine。
//
// 参数：
//   sub: 订阅者实例
func (b *Broadcaster) AddSubscriber(sub Subscriber) {
	if sub == nil {
		return
	}
	ch := make(chan BlockedEvent, b.queueSize)

	b.mu.Lock()
	b.subscribers = append(b.subscribers, ch)
	b.mu.Unlock()

	// 启动 worker goroutine 处理事件
	go func() {
		for {
			select {
			case <-b.ctx.Done():
				return
			case ev, ok := <-ch:
				if !ok {
					return
				}
				sub.HandleBlocked(b.ctx, ev)
			}
		}
	}()
}

// Publish 向所有订阅者发送事件。
//
// 当订阅者队列满时，会丢弃事件并记录日志（避免阻塞发布者）。
//
// 参数：
//   event: 要发送的事件
func (b *Broadcaster) Publish(event BlockedEvent) {
	if b.closed.Load() {
		return
	}

	b.mu.RLock()
	defer b.mu.RUnlock()

	for _, ch := range b.subscribers {
		select {
		case ch <- event:
			// 成功发送
		default:
			// 队列满，丢弃事件
			log.Warnf("[events] blocked-event queue full; dropping hostname %s", event.Hostname)
		}
	}
}

// Close 停止所有 worker 并关闭订阅者通道。
func (b *Broadcaster) Close() {
	if b.closed.Load() {
		return
	}

	b.cancel()

	b.mu.Lock()
	defer b.mu.Unlock()
	subs := b.subscribers
	b.subscribers = nil

	for _, ch := range subs {
		close(ch)
	}
	b.closed.Store(true)
}
