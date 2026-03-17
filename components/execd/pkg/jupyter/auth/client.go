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

// 认证类型常量定义

const (
	// AuthTypeNone 表示无认证模式
	AuthTypeNone = "none"

	// AuthTypeToken 表示 Token 认证模式
	AuthTypeToken = "token"

	// AuthTypeBasic 表示 Basic Auth 认证模式
	AuthTypeBasic = "basic"

	// AuthHeaderKey 认证请求头键名
	AuthHeaderKey = "Authorization"

	// AuthHeaderValuePrefix Token 认证请求头值前缀（"token "）
	AuthHeaderValuePrefix = "token "

	// AuthURLParamKey URL 查询参数中 token 的键名
	AuthURLParamKey = "token"
)

// NewAuth 创建一个新的空认证配置
//
// 返回值:
//   - *Auth: 空的认证对象，所有字段均为零值
//
// 使用示例:
//
//	auth := auth.NewAuth()
//	auth.Token = "my-token"
func NewAuth() *Auth {
	return &Auth{}
}

// IsValid 检查认证配置是否有效
//
// 有效认证配置定义为：
//   - Token 非空（Token 认证）
//   - 或 Username 和 Password 均非空（Basic 认证）
//
// 返回值:
//   - bool: 配置是否有效
func (a *Auth) IsValid() bool {
	return a.Token != "" || (a.Username != "" && a.Password != "")
}

// GetAuthType 获取认证类型
//
// 本方法是 Validate() 方法的别名，用于获取当前认证配置的类型。
//
// 返回值:
//   - string: 认证类型（"token"、"basic" 或 "none"）
func (a *Auth) GetAuthType() string {
	return a.Validate()
}
