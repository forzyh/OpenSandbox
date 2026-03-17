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

package runtime

import (
	"bufio"
	"bytes"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// tailStdPipe 流式读取日志文件的追加内容，直到进程结束
//
// 本函数定期读取日志文件的新内容并通过回调函数发送。
// 使用 ticker 每隔 100ms 检查一次文件是否有新内容。
//
// 参数:
//   - file: 日志文件路径
//   - onExecute: 读取到新内容时的回调函数
//   - done: 完成信号通道，用于通知停止读取
func (c *Controller) tailStdPipe(file string, onExecute func(text string), done <-chan struct{}) {
	lastPos := int64(0)
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()

	mutex := &sync.Mutex{}
	for {
		select {
		case <-done:
			// 收到完成信号，读取剩余内容并返回
			c.readFromPos(mutex, file, lastPos, onExecute, true)
			return
		case <-ticker.C:
			// 定期检查新内容
			newPos := c.readFromPos(mutex, file, lastPos, onExecute, false)
			lastPos = newPos
		}
	}
}

// getCommandKernel 获取命令执行上下文
//
// 本方法从 commandClientMap 中检索指定会话的命令内核。
//
// 参数:
//   - sessionID: 会话 ID
//
// 返回值:
//   - *commandKernel: 命令内核（如果不存在则返回 nil）
func (c *Controller) getCommandKernel(sessionID string) *commandKernel {
	if v, ok := c.commandClientMap.Load(sessionID); ok {
		if kernel, ok := v.(*commandKernel); ok {
			return kernel
		}
	}
	return nil
}

// storeCommandKernel 注册命令执行上下文
//
// 本方法将命令内核存储到 commandClientMap 中。
//
// 参数:
//   - sessionID: 会话 ID
//   - kernel: 命令内核实例
func (c *Controller) storeCommandKernel(sessionID string, kernel *commandKernel) {
	c.commandClientMap.Store(sessionID, kernel)
}

// stdLogDescriptor 创建用于捕获命令输出的临时文件
//
// 本函数为命令执行创建标准输出和标准错误的日志文件。
// 在打开文件之前会确保临时目录存在，这样即使/tmp 目录
// 被删除后重新创建，命令仍然可以正常工作。
//
// 参数:
//   - session: 会话 ID
//
// 返回值:
//   - io.WriteCloser: 标准输出文件
//   - io.WriteCloser: 标准错误文件
//   - error: 创建错误（如有）
func (c *Controller) stdLogDescriptor(session string) (io.WriteCloser, io.WriteCloser, error) {
	logDir := os.TempDir()
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return nil, nil, fmt.Errorf("failed to create temp dir %s: %w", logDir, err)
	}

	stdout, err := os.OpenFile(c.stdoutFileName(session), os.O_RDWR|os.O_CREATE|os.O_TRUNC, os.ModePerm)
	if err != nil {
		return nil, nil, err
	}
	stderr, err := os.OpenFile(c.stderrFileName(session), os.O_RDWR|os.O_CREATE|os.O_TRUNC, os.ModePerm)
	if err != nil {
		stdout.Close()
		return nil, nil, err
	}

	return stdout, stderr, nil
}

// combinedOutputDescriptor 创建用于捕获合并输出的临时文件
//
// 本函数为后台命令创建合并输出文件（stdout 和 stderr 合并）。
//
// 参数:
//   - session: 会话 ID
//
// 返回值:
//   - io.WriteCloser: 合并输出文件
//   - error: 创建错误（如有）
func (c *Controller) combinedOutputDescriptor(session string) (io.WriteCloser, error) {
	logDir := os.TempDir()
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		return nil, fmt.Errorf("failed to create temp dir %s: %w", logDir, err)
	}
	return os.OpenFile(c.combinedOutputFileName(session), os.O_RDWR|os.O_CREATE|os.O_TRUNC, os.ModePerm)
}

// stdoutFileName 构建标准输出日志文件路径
func (c *Controller) stdoutFileName(session string) string {
	return filepath.Join(os.TempDir(), session+".stdout")
}

// stderrFileName 构建标准错误日志文件路径
func (c *Controller) stderrFileName(session string) string {
	return filepath.Join(os.TempDir(), session+".stderr")
}

// combinedOutputFileName 构建合并输出日志文件路径
func (c *Controller) combinedOutputFileName(session string) string {
	return filepath.Join(os.TempDir(), session+".output")
}

// readFromPos 从文件的指定位置开始流式读取新内容
//
// 本函数从 startPos 位置开始读取文件内容，按行输出并通过回调函数发送。
// 如果 flushIncomplete 为 true，则即使最后一行没有换行符也会输出。
//
// 参数:
//   - mutex: 保护文件访问的互斥锁
//   - filepath: 文件路径
//   - startPos: 起始读取位置
//   - onExecute: 读取到内容时的回调函数
//   - flushIncomplete: 是否输出不完整的最后一行
//
// 返回值:
//   - int64: 新的读取位置
func (c *Controller) readFromPos(mutex *sync.Mutex, filepath string, startPos int64, onExecute func(string), flushIncomplete bool) int64 {
	// 尝试获取锁，如果获取失败返回 -1
	if !mutex.TryLock() {
		return -1
	}
	defer mutex.Unlock()

	file, err := os.Open(filepath)
	if err != nil {
		return startPos
	}
	defer file.Close()

	// 定位到起始位置
	_, _ = file.Seek(startPos, 0)

	reader := bufio.NewReader(file)
	var buffer bytes.Buffer
	var currentPos int64 = startPos

	for {
		b, err := reader.ReadByte()
		if err != nil {
			if err == io.EOF {
				// 如果缓冲区有内容但没有换行符，根据 flushIncomplete 决定是否输出
				if flushIncomplete && buffer.Len() > 0 {
					onExecute(buffer.String())
					buffer.Reset()
				}
			}
			break
		}
		currentPos++

		// 检查是否是行结束符
		if b == '\n' || b == '\r' {
			// 如果缓冲区有内容，输出这一行
			if buffer.Len() > 0 {
				onExecute(buffer.String())
				buffer.Reset()
			}
			// 跳过年结束符
			continue
		}

		buffer.WriteByte(b)
	}

	endPos, _ := file.Seek(0, 1)
	// 如果最后读取的位置没有以换行符结束，返回缓冲区起始位置，等待下次刷新
	if !flushIncomplete && buffer.Len() > 0 {
		return currentPos - int64(buffer.Len())
	}
	return endPos
}
