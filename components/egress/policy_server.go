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

// HTTP 策略服务器实现。
//
// 本文件实现了运行时更新出口策略的 HTTP API 服务器：
// - GET  /policy  : 返回当前生效的策略
// - POST /policy  : 替换策略（空 body 重置为默认拒绝所有）
// - PUT  /policy  : 同 POST
// - PATCH /policy : 合并添加新的出口规则
// - GET  /healthz : 健康检查端点
//
// 认证：
// 通过 OPENSANDBOX_EGRESS_TOKEN 环境变量设置令牌，
// 请求需在 OPENSANDBOX-EGRESS-AUTH 头中提供令牌。
package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/netip"
	"strings"
	"sync"
	"time"

	"github.com/alibaba/opensandbox/egress/pkg/constants"
	"github.com/alibaba/opensandbox/egress/pkg/log"
	"github.com/alibaba/opensandbox/egress/pkg/nftables"
	"github.com/alibaba/opensandbox/egress/pkg/policy"
)

// policyUpdater 定义策略更新接口。
//
// 用于抽象策略的读取和更新操作，便于测试和扩展。
type policyUpdater interface {
	CurrentPolicy() *policy.NetworkPolicy
	UpdatePolicy(*policy.NetworkPolicy)
}

// enforcementReporter 定义执行模式报告接口。
type enforcementReporter interface {
	EnforcementMode() string
}

// nftApplier 定义 nftables 策略应用接口。
type nftApplier interface {
	ApplyStatic(context.Context, *policy.NetworkPolicy) error
	AddResolvedIPs(context.Context, []nftables.ResolvedIP) error
}

// startPolicyServer 启动 HTTP 策略服务器。
//
// 支持的端点：
// - GET  /policy : 返回当前生效的策略
// - POST /policy : 替换策略；空 body 重置为默认拒绝所有
// - PUT  /policy : 同 POST
// - PATCH /policy : 合并添加新的出口规则
// - GET  /healthz : 健康检查
//
// 参数：
//   ctx: 上下文，用于优雅关闭
//   proxy: DNS 代理实例，用于更新策略
//   nft: nftables 管理器，用于应用静态策略
//   enforcementMode: 执行模式（"dns" 或 "dns+nft"）
//   addr: 监听地址
//   token: 认证令牌（可选）
//   nameserverIPs: nameserver IP 列表，合并到每个应用的策略中
//
// 返回：
//   启动错误（如有）
func startPolicyServer(ctx context.Context, proxy policyUpdater, nft nftApplier, enforcementMode string, addr string, token string, nameserverIPs []netip.Addr) error {
	mux := http.NewServeMux()
	handler := &policyServer{proxy: proxy, nft: nft, token: token, enforcementMode: enforcementMode, nameserverIPs: nameserverIPs}
	mux.HandleFunc("/policy", handler.handlePolicy)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})

	srv := &http.Server{Addr: addr, Handler: mux}
	handler.server = srv

	// 上下文结束时优雅关闭服务器
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := srv.Shutdown(shutdownCtx); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Warnf("policy server shutdown error: %v", err)
		}
	}()

	// 在后台启动 HTTP 服务器
	errCh := make(chan error, 1)
	go func() {
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
	}()

	// 等待启动完成或错误
	select {
	case err := <-errCh:
		return err
	case <-time.After(200 * time.Millisecond):
		// 假设启动成功，继续在后台记录错误
		go func() {
			if err := <-errCh; err != nil {
				log.Errorf("policy server error: %v", err)
			}
		}()
		return nil
	}
}

// policyServer HTTP 策略服务器结构体。
type policyServer struct {
	proxy           policyUpdater
	nft             nftApplier
	server          *http.Server
	token           string
	enforcementMode string
	nameserverIPs   []netip.Addr
	mu              sync.Mutex // 序列化读 - 合并 - 应用操作，避免 POST/PATCH 之间的更新丢失
}

// policyStatusResponse 策略状态响应结构。
type policyStatusResponse struct {
	Status          string `json:"status,omitempty"`
	Mode            string `json:"mode,omitempty"`
	EnforcementMode string `json:"enforcementMode,omitempty"`
	Reason          string `json:"reason,omitempty"`
	Policy          any    `json:"policy,omitempty"`
}

// handlePolicy 处理 /policy 端点请求。
//
// 根据请求方法路由到不同的处理函数：
// - GET: 获取当前策略
// - POST/PUT: 替换策略
// - PATCH: 合并添加规则
func (s *policyServer) handlePolicy(w http.ResponseWriter, r *http.Request) {
	if !s.authorize(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	switch r.Method {
	case http.MethodGet:
		s.handleGet(w)
	case http.MethodPost, http.MethodPut:
		s.handlePost(w, r)
	case http.MethodPatch:
		s.handlePatch(w, r)
	default:
		w.Header().Set("Allow", "GET, POST, PUT, PATCH")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

// handleGet 处理 GET 请求，返回当前策略。
func (s *policyServer) handleGet(w http.ResponseWriter) {
	current := s.proxy.CurrentPolicy()
	mode := modeFromPolicy(current)
	writeJSON(w, http.StatusOK, policyStatusResponse{
		Status:          "ok",
		Mode:            mode,
		EnforcementMode: s.enforcementMode,
		Policy:          current,
	})
}

// handlePost 处理 POST/PUT 请求，替换策略。
//
// 空 body 会重置为默认拒绝所有策略。
func (s *policyServer) handlePost(w http.ResponseWriter, r *http.Request) {
	defer r.Body.Close()
	s.mu.Lock()
	defer s.mu.Unlock()

	// 读取请求体（最大 1MB）
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20)) // 1MB limit
	if err != nil {
		http.Error(w, fmt.Sprintf("failed to read body: %v", err), http.StatusBadRequest)
		return
	}
	raw := strings.TrimSpace(string(body))

	// 空 body：重置为默认拒绝所有
	if raw == "" {
		log.Infof("policy API: reset to default deny-all")
		def := policy.DefaultDenyPolicy()
		if s.nft != nil {
			defWithNS := def.WithExtraAllowIPs(s.nameserverIPs)
			if err := s.nft.ApplyStatic(r.Context(), defWithNS); err != nil {
				log.Errorf("policy API: nftables apply failed on reset: %v", err)
				http.Error(w, fmt.Sprintf("failed to apply nftables: %v", err), http.StatusInternalServerError)
				return
			}
		}
		s.proxy.UpdatePolicy(def)
		log.Infof("policy API: proxy and nftables updated to deny_all")
		writeJSON(w, http.StatusOK, policyStatusResponse{
			Status: "ok",
			Mode:   "deny_all",
			Reason: "policy reset to default deny-all",
		})
		return
	}

	// 解析新策略
	pol, err := policy.ParsePolicy(raw)
	if err != nil {
		http.Error(w, fmt.Sprintf("invalid policy: %v", err), http.StatusBadRequest)
		return
	}
	mode := modeFromPolicy(pol)
	log.Infof("policy API: updating policy to mode=%s, enforcement=%s", mode, s.enforcementMode)

	// 应用到 nftables
	if s.nft != nil {
		polWithNS := pol.WithExtraAllowIPs(s.nameserverIPs)
		if err := s.nft.ApplyStatic(r.Context(), polWithNS); err != nil {
			log.Errorf("policy API: nftables apply failed: %v", err)
			http.Error(w, fmt.Sprintf("failed to apply nftables policy: %v", err), http.StatusInternalServerError)
			return
		}
	}
	s.proxy.UpdatePolicy(pol)
	log.Infof("policy API: proxy and nftables updated successfully")
	writeJSON(w, http.StatusOK, policyStatusResponse{
		Status:          "ok",
		Mode:            mode,
		EnforcementMode: s.enforcementMode,
	})
}

// handlePatch 处理 PATCH 请求，合并添加出口规则。
//
// 请求 body 格式：{"egress":[{"action":"allow","target":"example.com"}, ...]}
// 新规则会覆盖同名的已有规则（后写入者获胜）。
func (s *policyServer) handlePatch(w http.ResponseWriter, r *http.Request) {
	defer r.Body.Close()
	s.mu.Lock()
	defer s.mu.Unlock()

	// 读取请求体（最大 1MB）
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20)) // 1MB limit
	if err != nil {
		http.Error(w, fmt.Sprintf("failed to read body: %v", err), http.StatusBadRequest)
		return
	}
	raw := strings.TrimSpace(string(body))
	if raw == "" {
		http.Error(w, "patch body cannot be empty", http.StatusBadRequest)
		return
	}

	// 解析补丁规则
	var patchRules []policy.EgressRule
	if err = json.Unmarshal([]byte(raw), &patchRules); err != nil {
		http.Error(w, fmt.Sprintf("invalid patch rules: %v", err), http.StatusBadRequest)
		return
	}
	if len(patchRules) == 0 {
		http.Error(w, "patch must include at least one egress rule", http.StatusBadRequest)
		return
	}

	// 获取当前策略作为基础
	base := s.proxy.CurrentPolicy()
	if base == nil {
		base = policy.DefaultDenyPolicy()
	}
	// 复制策略，避免修改原策略
	baseCopy := *base
	baseCopy.Egress = append([]policy.EgressRule(nil), base.Egress...)

	// 合并规则
	merged := mergeEgressRules(baseCopy.Egress, patchRules)

	// 重新解析以规范化目标和动作
	rawMerged, _ := json.Marshal(policy.NetworkPolicy{
		DefaultAction: baseCopy.DefaultAction,
		Egress:        merged,
	})
	newPolicy, err := policy.ParsePolicy(string(rawMerged))
	if err != nil {
		http.Error(w, fmt.Sprintf("invalid merged policy: %v", err), http.StatusBadRequest)
		return
	}

	mode := modeFromPolicy(newPolicy)
	log.Infof("policy API: patching policy with %d new rule(s), mode=%s, enforcement=%s", len(patchRules), mode, s.enforcementMode)

	// 应用到 nftables
	if s.nft != nil {
		polWithNS := newPolicy.WithExtraAllowIPs(s.nameserverIPs)
		if err := s.nft.ApplyStatic(r.Context(), polWithNS); err != nil {
			log.Errorf("policy API: nftables apply failed on patch: %v", err)
			http.Error(w, fmt.Sprintf("failed to apply nftables policy: %v", err), http.StatusInternalServerError)
			return
		}
	}
	s.proxy.UpdatePolicy(newPolicy)
	log.Infof("policy API: patch applied successfully")
	writeJSON(w, http.StatusOK, policyStatusResponse{
		Status:          "ok",
		Mode:            mode,
		EnforcementMode: s.enforcementMode,
	})
}

// authorize 检查请求是否通过认证。
//
// 如果未设置令牌，所有请求都被授权。
// 否则，请求必须在 OPENSANDBOX-EGRESS-AUTH 头中提供匹配的令牌。
func (s *policyServer) authorize(r *http.Request) bool {
	if s.token == "" {
		return true
	}
	provided := r.Header.Get(constants.EgressAuthTokenHeader)
	if provided == "" {
		return false
	}
	if len(provided) != len(s.token) {
		return false
	}
	return subtle.ConstantTimeCompare([]byte(provided), []byte(s.token)) == 1
}

// writeJSON 写入 JSON 响应。
func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

// modeFromPolicy 根据策略确定模式字符串。
func modeFromPolicy(p *policy.NetworkPolicy) string {
	if p == nil {
		return "deny_all"
	}
	if p.DefaultAction == policy.ActionAllow && len(p.Egress) == 0 {
		return "allow_all"
	} else if p.DefaultAction == policy.ActionDeny && len(p.Egress) == 0 {
		return "deny_all"
	}
	return "enforcing"
}

// mergeEgressRules 合并基础规则和新规则，去重（按目标，后写入者获胜）。
//
// 参数：
//   base: 基础规则列表
//   additions: 要添加的规则列表
//
// 返回：
//   合并后的规则列表
func mergeEgressRules(base, additions []policy.EgressRule) []policy.EgressRule {
	if len(additions) == 0 {
		return base
	}
	out := make([]policy.EgressRule, 0, len(base)+len(additions))
	seen := make(map[string]struct{})

	// 优先级：新规则优先，基础规则仅在不被覆盖时保留
	for _, r := range additions {
		key := mergeKey(r)
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		out = append(out, r)
	}
	for _, r := range base {
		key := mergeKey(r)
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		out = append(out, r)
	}
	return out
}

// mergeKey 生成规则的合并键。
//
// 域名目标会被转换为小写以便去重；
// IP/CIDR 目标保持原样。
func mergeKey(r policy.EgressRule) string {
	if r.Target == "" {
		return r.Target
	}
	return strings.ToLower(r.Target)
}
