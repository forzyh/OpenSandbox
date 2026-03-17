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

package auth

import (
	"fmt"
	"net/url"
)

// Auth 表示 Jupyter 服务器的认证配置
//
// Auth 结构体封装了与 Jupyter 服务器通信所需的所有认证信息，
// 支持 Token 认证和 Basic 认证两种方式：
//   - Token 认证：仅需设置 Token 字段
//   - Basic 认证：需设置 Username 和 Password 字段
//
// 使用场景：
//   - 创建认证客户端：auth.NewClient(httpClient, authConfig)
//   - 验证认证配置：auth.IsValid()
//   - 获取认证类型：auth.Validate() 返回 "token"、"basic" 或 "none"
//   - 将 token 添加到 URL：auth.AddAuthToURL(baseURL)
type Auth struct {
	// Token Token 认证令牌，用于 Authorization 请求头或 URL 查询参数
	Token string

	// Username Basic 认证用户名
	Username string

	// Password Basic 认证密码
	Password string
}

// NewTokenAuth 创建基于 Token 的认证配置
//
// 参数:
//   - token: Jupyter 服务器的认证令牌
//
// 返回值:
//   - *Auth: 配置好 Token 的认证对象
func NewTokenAuth(token string) *Auth {
	return &Auth{
		Token: token,
	}
}

// NewBasicAuth 创建基于 Basic Auth 的认证配置
//
// 参数:
//   - username: 用户名
//   - password: 密码
//
// 返回值:
//   - *Auth: 配置好用户名和密码的认证对象
func NewBasicAuth(username, password string) *Auth {
	return &Auth{
		Username: username,
		Password: password,
	}
}

// Validate 检查当前认证配置的模式
//
// 按以下优先级判断认证类型：
//   1. 如果 Token 非空，返回 "token"
//   2. 如果 Username 非空，返回 "basic"
//   3. 否则返回 "none"
//
// 返回值:
//   - string: 认证类型（"token"、"basic" 或 "none"）
func (a *Auth) Validate() string {
	if a.Token != "" {
		return "token"
	}
	if a.Username != "" {
		return "basic"
	}
	return "none"
}

// AddAuthToURL 将认证信息（token）添加到 URL 查询参数中
//
// 本方法解析给定的 baseURL，如果配置了 Token，则将其作为查询参数
// 添加到 URL 中（key 为 "token"）。如果未配置 Token，则返回原 URL。
//
// 参数:
//   - baseURL: 基础 URL
//
// 返回值:
//   - string: 添加了认证参数的完整 URL
//   - error: URL 解析错误（如有）
func (a *Auth) AddAuthToURL(baseURL string) (string, error) {
	parsedURL, err := url.Parse(baseURL)
	if err != nil {
		return "", fmt.Errorf("failed to parse URL: %w", err)
	}

	query := parsedURL.Query()

	if a.Token != "" {
		query.Set("token", a.Token)
	}

	parsedURL.RawQuery = query.Encode()
	return parsedURL.String(), nil
}
