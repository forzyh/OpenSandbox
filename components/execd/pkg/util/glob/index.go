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

package glob

// isValidPattern 检查 glob 模式是否格式正确
//
// 本函数验证模式的语法正确性，检查：
//   - 转义字符后是否有有效字符
//   - 字符类 [...] 是否正确闭合
//   - 花括号 {...} 是否正确匹配
//
// 参数:
//   - s: 要验证的模式字符串
//   - separator: 路径分隔符（用于确定是否需要特殊处理）
//
// 返回值:
//   - bool: 模式是否有效
//
//nolint:gocognit
func isValidPattern(s string, separator rune) bool {
	altDepth := 0 // 花括号嵌套深度
	l := len(s)
VALIDATE:
	for i := 0; i < l; i++ {
		switch s[i] {
		case '\\':
			// 处理转义字符
			if separator != '\\' {
				// 转义下一个字符
				if i++; i >= l {
					// 模式在转义字符后结束，无效
					return false
				}
			}
			continue

		case '[':
			// 处理字符类开始
			if i++; i >= l {
				// 字符类未闭合，无效
				return false
			}
			// 检查否定字符类
			if s[i] == '^' || s[i] == '!' {
				i++
			}
			if i >= l || s[i] == ']' {
				// 空字符类，无效
				return false
			}

			// 扫描字符类内容直到闭合的 ]
			for ; i < l; i++ {
				if separator != '\\' && s[i] == '\\' {
					// 跳过转义字符
					i++
				} else if s[i] == ']' {
					// 找到闭合的 ]，继续验证
					continue VALIDATE
				}
			}

			// 未找到闭合的 ]，无效
			return false

		case '{':
			// 花括号嵌套深度加 1
			altDepth++
			continue

		case '}':
			// 花括号嵌套深度减 1
			if altDepth == 0 {
				// 没有匹配的 {，无效
				return false
			}
			altDepth--
			continue
		}
	}

	// 所有花括号必须闭合
	return altDepth == 0
}
