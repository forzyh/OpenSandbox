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
//
// 本代码基于或衍生自 doublestar
// Copyright (c) 2014 Bob Matcuk
// 根据 MIT 许可证授权
// https://github.com/bmatcuk/doublestar/blob/master/LICENSE

// Package glob 提供兼容 doublestar 语义的文件路径匹配功能
//
// 本包实现了 glob 模式匹配，支持以下通配符：
//   - * : 匹配任意数量的非路径分隔符字符
//   - ** : 匹配任意数量的任意字符（包括路径分隔符）
//   - ? : 匹配单个非路径分隔符字符
//   - [abc] : 匹配字符集合中的任意一个字符
//   - [a-z] : 匹配字符范围内的任意一个字符
//   - [!abc] 或 [^abc] : 匹配不在字符集合中的任意字符
//   - {a,b,c} : 匹配任意一个备选模式
//   - !(pattern) : 否定匹配，当 pattern 不匹配时返回 true
//   - \ : 转义字符
//
// 主要函数：
//   - PathMatch: filepath.Match 的兼容版本，但支持 doublestar 语义
package glob

import (
	"path/filepath"
	"unicode/utf8"

	globutil "github.com/bmatcuk/doublestar/v4"
)

// PathMatch 执行路径模式匹配
//
// 本函数是 filepath.Match 的兼容版本，但支持 doublestar 语义。
// 它可以匹配包含 ** 通配符的模式，** 可以跨越目录层级。
//
// 参数:
//   - pattern: glob 模式字符串
//   - name: 要匹配的路径名
//
// 返回值:
//   - bool: 是否匹配成功
//   - error: 模式格式错误（如有）
func PathMatch(pattern, name string) (bool, error) {
	return matchWithSeparator(pattern, name, filepath.Separator, true)
}

// matchWithSeparator 使用指定的路径分隔符进行模式匹配
//
// 本函数是 PathMatch 的内部实现，允许自定义路径分隔符。
//
// 参数:
//   - pattern: glob 模式字符串
//   - name: 要匹配的路径名
//   - separator: 路径分隔符
//   - validate: 是否验证剩余模式的有效性
//
// 返回值:
//   - bool: 是否匹配成功
//   - error: 模式格式错误（如有）
func matchWithSeparator(pattern, name string, separator rune, validate bool) (matched bool, err error) {
	return doMatchWithSeparator(pattern, name, separator, validate, -1, -1, -1, -1, 0, 0)
}

// doMatchWithSeparator 执行实际的模式匹配逻辑
//
// 本函数使用回溯算法实现 glob 模式匹配，支持：
//   - 单星号 (*)：匹配非分隔符字符
//   - 双星号 (**)：匹配任意字符（包括分隔符）
//   - 问号 (?)：匹配单个非分隔符字符
//   - 字符类 ([abc])：匹配字符集合
//   - 否定模式 (!(pattern))：当 pattern 不匹配时返回 true
//   - 备选模式 ({a,b,c})：匹配任意一个备选
//
// 回溯机制：
//   - doublestarPatternBacktrack/NameBacktrack: ** 的回溯位置
//   - starPatternBacktrack/NameBacktrack: * 的回溯位置
//
// 参数:
//   - pattern: glob 模式字符串
//   - name: 要匹配的路径名
//   - separator: 路径分隔符
//   - validate: 是否验证剩余模式
//   - doublestarPatternBacktrack: ** 模式回溯位置
//   - doublestarNameBacktrack: ** 名称回溯位置
//   - starPatternBacktrack: * 模式回溯位置
//   - starNameBacktrack: * 名称回溯位置
//   - patIdx: 当前模式索引
//   - nameIdx: 当前名称索引
//
// 返回值:
//   - bool: 是否匹配成功
//   - error: 模式格式错误（如有）
//
//nolint:gocognit,nestif,gocyclo,maintidx
func doMatchWithSeparator(pattern, name string, separator rune, validate bool, doublestarPatternBacktrack, doublestarNameBacktrack, starPatternBacktrack, starNameBacktrack, patIdx, nameIdx int) (matched bool, err error) {
	patLen := len(pattern)
	nameLen := len(name)
	startOfSegment := true
MATCH:
	for nameIdx < nameLen {
		if patIdx < patLen {
			switch pattern[patIdx] {
			case '*':
				// 处理星号通配符
				if patIdx++; patIdx < patLen && pattern[patIdx] == '*' {
					// 双星号 **
					patIdx++
					if startOfSegment {
						if patIdx >= patLen {
							// 模式以 /** 结尾：返回 true
							return true, nil
						}

						// 双星号后必须跟路径分隔符
						patRune, patRuneLen := utf8.DecodeRuneInString(pattern[patIdx:])
						if patRune == separator {
							patIdx += patRuneLen

							doublestarPatternBacktrack = patIdx
							doublestarNameBacktrack = nameIdx
							starPatternBacktrack = -1
							starNameBacktrack = -1
							continue
						}
					}
				}
				startOfSegment = false

				// 单星号回溯点
				starPatternBacktrack = patIdx
				starNameBacktrack = nameIdx
				continue

			case '?':
				// 问号匹配单个非分隔符字符
				startOfSegment = false
				nameRune, nameRuneLen := utf8.DecodeRuneInString(name[nameIdx:])
				if nameRune == separator {
					// ? 不能匹配分隔符
					break
				}

				patIdx++
				nameIdx += nameRuneLen
				continue

			case '[':
				// 字符类匹配
				startOfSegment = false
				if patIdx++; patIdx >= patLen {
					// 字符类未结束
					return false, globutil.ErrBadPattern
				}
				nameRune, nameRuneLen := utf8.DecodeRuneInString(name[nameIdx:])

				matched := false
				negate := pattern[patIdx] == '!' || pattern[patIdx] == '^'
				if negate {
					patIdx++
				}

				if patIdx >= patLen || pattern[patIdx] == ']' {
					// 字符类未结束或空字符类
					return false, globutil.ErrBadPattern
				}

				last := utf8.MaxRune
				for patIdx < patLen && pattern[patIdx] != ']' {
					patRune, patRuneLen := utf8.DecodeRuneInString(pattern[patIdx:])
					patIdx += patRuneLen

					// 匹配范围
					if last < utf8.MaxRune && patRune == '-' && patIdx < patLen && pattern[patIdx] != ']' {
						if pattern[patIdx] == '\\' {
							// 下一个字符被转义
							patIdx++
						}
						patRune, patRuneLen = utf8.DecodeRuneInString(pattern[patIdx:])
						patIdx += patRuneLen

						if last <= nameRune && nameRune <= patRune {
							matched = true
							break
						}

						// 未匹配范围 - 重置 last
						last = utf8.MaxRune
						continue
					}

					// 不是范围 - 检查下一个字符是否被转义
					if patRune == '\\' {
						patRune, patRuneLen = utf8.DecodeRuneInString(pattern[patIdx:])
						patIdx += patRuneLen
					}

					// 检查是否匹配
					if patRune == nameRune {
						matched = true
						break
					}

					// 尚未匹配
					last = patRune
				}

				if matched == negate {
					// 匹配失败
					if patIdx >= patLen {
						return false, globutil.ErrBadPattern
					}
					break
				}

				closingIdx := findUnescapedByteIndex(pattern[patIdx:], ']', true)
				if closingIdx == -1 {
					// 没有闭合的 ]
					return false, globutil.ErrBadPattern
				}

				patIdx += closingIdx + 1
				nameIdx += nameRuneLen
				continue

			case '!':
				// 否定模式 !(pattern)
				negateIdx := patIdx
				patIdx++
				closingIdx := findMatchedClosingBracketIndex(pattern[patIdx:], separator != '\\')
				if closingIdx == -1 {
					return false, globutil.ErrBadPattern
				}
				closingIdx += patIdx

				result, err := doMatchWithSeparator(pattern[:negateIdx]+pattern[patIdx+1:closingIdx]+pattern[closingIdx+1:], name, separator, validate, doublestarPatternBacktrack, doublestarNameBacktrack, starPatternBacktrack, starNameBacktrack, negateIdx, nameIdx)
				if err != nil {
					return false, err
				} else if !result {
					return true, nil
				} else {
					return false, nil
				}

			case '{':
				// 备选模式 {a,b,c}
				startOfSegment = false
				beforeIdx := patIdx
				patIdx++
				closingIdx := findMatchedClosingAltIndex(pattern[patIdx:], separator != '\\')
				if closingIdx == -1 {
					// 没有闭合的 }
					return false, globutil.ErrBadPattern
				}
				closingIdx += patIdx

				for {
					commaIdx := findNextCommaIndex(pattern[patIdx:closingIdx], separator != '\\')
					if commaIdx == -1 {
						break
					}
					commaIdx += patIdx

					result, err := doMatchWithSeparator(pattern[:beforeIdx]+pattern[patIdx:commaIdx]+pattern[closingIdx+1:], name, separator, validate, doublestarPatternBacktrack, doublestarNameBacktrack, starPatternBacktrack, starNameBacktrack, beforeIdx, nameIdx)
					if result || err != nil {
						return result, err
					}

					patIdx = commaIdx + 1
				}
				return doMatchWithSeparator(pattern[:beforeIdx]+pattern[patIdx:closingIdx]+pattern[closingIdx+1:], name, separator, validate, doublestarPatternBacktrack, doublestarNameBacktrack, starPatternBacktrack, starNameBacktrack, beforeIdx, nameIdx)

			case '\\':
				// 转义字符
				if separator != '\\' {
					// 下一个字符被转义 - 字面匹配
					if patIdx++; patIdx >= patLen {
						// 模式结束
						return false, globutil.ErrBadPattern
					}
				}
				fallthrough

			default:
				// 字面字符匹配
				patRune, patRuneLen := utf8.DecodeRuneInString(pattern[patIdx:])
				nameRune, nameRuneLen := utf8.DecodeRuneInString(name[nameIdx:])
				if patRune != nameRune {
					if separator != '\\' && patIdx > 0 && pattern[patIdx-1] == '\\' {
						// 如果这个字符本应被转义，需要回退 patIdx
						patIdx--
					}
					break
				}

				patIdx += patRuneLen
				nameIdx += nameRuneLen
				startOfSegment = patRune == separator
				continue
			}
		}

		// * 回溯：仅当 name 字符不是分隔符时
		if starPatternBacktrack >= 0 {
			nameRune, nameRuneLen := utf8.DecodeRuneInString(name[starNameBacktrack:])
			if nameRune != separator {
				starNameBacktrack += nameRuneLen
				patIdx = starPatternBacktrack
				nameIdx = starNameBacktrack
				startOfSegment = false
				continue
			}
		}

		// ** 回溯：推进 name 到下一个分隔符
		if doublestarPatternBacktrack >= 0 {
			nameIdx = doublestarNameBacktrack
			for nameIdx < nameLen {
				nameRune, nameRuneLen := utf8.DecodeRuneInString(name[nameIdx:])
				nameIdx += nameRuneLen
				if nameRune == separator {
					doublestarNameBacktrack = nameIdx
					patIdx = doublestarPatternBacktrack
					startOfSegment = true
					continue MATCH
				}
			}
		}

		// 验证剩余模式
		if validate && patIdx < patLen && !isValidPattern(pattern[patIdx:], separator) {
			return false, globutil.ErrBadPattern
		}
		return false, nil
	}

	if nameIdx < nameLen {
		// pattern 在 name 之前结束
		return false, nil
	}

	// name 已结束；只有 pattern 也结束时才算匹配成功
	return isZeroLengthPattern(pattern[patIdx:], separator)
}

// isZeroLengthPattern 检查是否为零长度模式
//
// 零长度模式包括：
//   - 空字符串
//   - 单个 *
//   - 单个 **
//   - 路径分隔符 + **
//
// 特殊情况：/** 是特殊模式，path/to/a/** 应该匹配 path/to/a 下的所有内容
//
// 参数:
//   - pattern: 待检查的模式
//   - separator: 路径分隔符
//
// 返回值:
//   - bool: 是否为零长度模式
//   - error: 模式格式错误（如有）
//
// nolint:nakedret
func isZeroLengthPattern(pattern string, separator rune) (ret bool, err error) {
	// /** 是特殊模式
	if pattern == "" || pattern == "*" || pattern == "**" || pattern == string(separator)+"**" {
		return true, nil
	}

	if pattern[0] == '{' {
		closingIdx := findMatchedClosingAltIndex(pattern[1:], separator != '\\')
		if closingIdx == -1 {
			// 没有闭合的 }
			return false, globutil.ErrBadPattern
		}
		closingIdx += 1

		patIdx := 1
		for {
			commaIdx := findNextCommaIndex(pattern[patIdx:closingIdx], separator != '\\')
			if commaIdx == -1 {
				break
			}
			commaIdx += patIdx

			ret, err = isZeroLengthPattern(pattern[patIdx:commaIdx]+pattern[closingIdx+1:], separator)
			if ret || err != nil {
				return
			}

			patIdx = commaIdx + 1
		}
		return isZeroLengthPattern(pattern[patIdx:closingIdx]+pattern[closingIdx+1:], separator)
	}

	// 验证剩余模式
	if !isValidPattern(pattern, separator) {
		return false, globutil.ErrBadPattern
	}
	return false, nil
}
