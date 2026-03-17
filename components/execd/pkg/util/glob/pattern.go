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

// findUnescapedByteIndex 查找字符串中未转义字符的位置
//
// 本函数从左到右扫描字符串，查找第一个未转义的目标字符。
// 如果 allowEscaping 为 true，则跳过被反斜杠转义的字符。
//
// 参数:
//   - s: 要搜索的字符串
//   - c: 要查找的目标字符
//   - allowEscaping: 是否允许转义（true 时跳过 \X 形式的转义序列）
//
// 返回值:
//   - int: 找到的字符索引，未找到返回 -1
func findUnescapedByteIndex(s string, c byte, allowEscaping bool) int {
	l := len(s)
	for i := 0; i < l; i++ {
		if allowEscaping && s[i] == '\\' {
			// 跳过转义序列的下一个字符
			i++
		} else if s[i] == c {
			return i
		}
	}
	return -1
}

// findMatchedClosingAltIndex 查找与 { 匹配的 } 的位置
//
// 本函数用于处理备选模式 {a,b,c}，找到与起始 { 匹配的闭合 }。
// 支持嵌套的备选模式和转义字符。
//
// 参数:
//   - s: 要搜索的字符串（从 { 之后开始）
//   - allowEscaping: 是否允许转义
//
// 返回值:
//   - int: 匹配的 } 的索引，未找到返回 -1
func findMatchedClosingAltIndex(s string, allowEscaping bool) int {
	return findMatchedClosingSymbolsIndex(s, allowEscaping, '{', '}', 1)
}

// findMatchedClosingBracketIndex 查找与 ( 匹配的 ) 的位置
//
// 本函数用于处理否定模式 !(pattern)，找到与起始 ( 匹配的闭合 )。
//
// 参数:
//   - s: 要搜索的字符串（从 ( 之后开始）
//   - allowEscaping: 是否允许转义
//
// 返回值:
//   - int: 匹配的 ) 的索引，未找到返回 -1
func findMatchedClosingBracketIndex(s string, allowEscaping bool) int {
	return findMatchedClosingSymbolsIndex(s, allowEscaping, '(', ')', 0)
}

// findNextCommaIndex 返回嵌套花括号外的下一个逗号的索引
//
// 本函数用于处理备选模式 {a,b,c}，找到分隔备选方案的逗号。
// 只返回最外层花括号内的逗号，忽略嵌套花括号内的逗号。
//
// 参数:
//   - s: 要搜索的字符串
//   - allowEscaping: 是否允许转义
//
// 返回值:
//   - int: 逗号的索引，未找到返回 -1
func findNextCommaIndex(s string, allowEscaping bool) int {
	alts := 1 // 当前嵌套层级
	l := len(s)
	for i := 0; i < l; i++ {
		if allowEscaping && s[i] == '\\' {
			// 跳过转义字符
			i++
		} else if s[i] == '{' {
			// 进入嵌套层级
			alts++
		} else if s[i] == '}' {
			// 退出嵌套层级
			alts--
		} else if s[i] == ',' && alts == 1 {
			// 找到最外层的逗号
			return i
		}
	}
	return -1
}

// findMatchedClosingSymbolsIndex 查找匹配的闭合符号
//
// 本函数是通用的括号匹配函数，用于查找与起始符号匹配的闭合符号。
// 支持嵌套和转义字符。
//
// 参数:
//   - s: 要搜索的字符串
//   - allowEscaping: 是否允许转义
//   - left: 起始符号（如 '{' 或 '('）
//   - right: 闭合符号（如 '}' 或 ')'）
//   - begin: 初始嵌套层级（通常为 0 或 1）
//
// 返回值:
//   - int: 匹配的闭合符号的索引，未找到返回 -1
func findMatchedClosingSymbolsIndex(s string, allowEscaping bool, left, right uint8, begin int) int {
	l := len(s)
	for i := 0; i < l; i++ {
		if allowEscaping && s[i] == '\\' {
			// 跳过转义字符
			i++
		} else if s[i] == left {
			// 进入嵌套层级
			begin++
		} else if s[i] == right {
			// 退出嵌套层级
			if begin--; begin == 0 {
				// 找到匹配的闭合符号
				return i
			}
		}
	}
	return -1
}
