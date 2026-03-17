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
	"context"
	"database/sql"
	"fmt"
	"net/http"
	"sync"
	"time"

	"k8s.io/apimachinery/pkg/util/wait"

	"github.com/alibaba/opensandbox/execd/pkg/jupyter"
	jupytersession "github.com/alibaba/opensandbox/execd/pkg/jupyter/session"
	"github.com/alibaba/opensandbox/execd/pkg/log"
)

var kernelWaitingBackoff = wait.Backoff{
	Steps:    60,
	Duration: 500 * time.Millisecond,
	Factor:   1.5,
	Jitter:   0.1,
}

// Controller 运行时控制器，管理多种代码执行后端
// 详细说明请参考 ctrl.go 文件
type Controller struct {
	baseURL                 string
	token                   string
	mu                      sync.RWMutex
	jupyterClientMap        sync.Map // map[sessionID]*jupyterKernel
	defaultLanguageSessions sync.Map // map[Language]string
	commandClientMap        sync.Map // map[sessionID]*commandKernel
	bashSessionClientMap    sync.Map // map[sessionID]*bashSession
	db                      *sql.DB
	dbOnce                  sync.Once
}

type jupyterKernel struct {
	mu       sync.Mutex
	kernelID string
	client   *jupyter.Client
	language Language
}

type commandKernel struct {
	pid          int
	stdoutPath   string
	stderrPath   string
	startedAt    time.Time
	finishedAt   *time.Time
	exitCode     *int
	errMsg       string
	running      bool
	isBackground bool
	content      string
}

// NewController 创建运行时控制器
func NewController(baseURL, token string) *Controller {
	return &Controller{
		baseURL: baseURL,
		token:   token,
	}
}

// Execute 分发执行请求到相应后端
func (c *Controller) Execute(request *ExecuteCodeRequest) error {
	var cancel context.CancelFunc
	var ctx context.Context
	if request.Timeout > 0 {
		ctx, cancel = context.WithTimeout(context.Background(), request.Timeout)
	} else {
		ctx, cancel = context.WithCancel(context.Background())
	}

	switch request.Language {
	case Command:
		defer cancel()
		return c.runCommand(ctx, request)
	case BackgroundCommand:
		return c.runBackgroundCommand(ctx, cancel, request)
	case Bash, Python, Java, JavaScript, TypeScript, Go:
		defer cancel()
		return c.runJupyter(ctx, request)
	case SQL:
		defer cancel()
		return c.runSQL(ctx, request)
	default:
		defer cancel()
		return fmt.Errorf("unknown language: %s", request.Language)
	}
}

// CreateContext 创建内核支持的会话并返回会话 ID
//
// 本方法为指定语言创建一个新的 Jupyter 会话上下文。
// Bash 语言使用 Jupyter 内核像其他语言一样执行；
// 如需基于管道的 Bash 会话，请使用 CreateBashSession（会话 API）。
//
// 参数:
//   - req: 创建上下文请求
//
// 返回值:
//   - string: 会话 ID
//   - error: 创建错误（如有）
func (c *Controller) CreateContext(req *CreateContextRequest) (string, error) {
	var (
		client  *jupyter.Client
		session *jupytersession.Session
		err     error
	)

	// 使用重试机制创建 Jupyter 会话
	err = retry.OnError(kernelWaitingBackoff, func(err error) bool {
		log.Error("failed to create session, retrying: %v", err)
		return err != nil
	}, func() error {
		client, session, err = c.createJupyterContext(*req)
		return err
	})
	if err != nil {
		return "", err
	}

	// 存储内核信息
	kernel := &jupyterKernel{
		kernelID: session.Kernel.ID,
		client:   client,
		language: req.Language,
	}
	c.storeJupyterKernel(session.ID, kernel)

	// 设置工作目录
	err = c.setWorkingDir(kernel, req)
	if err != nil {
		return "", fmt.Errorf("failed to setup working dir: %w", err)
	}

	return session.ID, nil
}

// DeleteContext 删除会话并清理资源
func (c *Controller) DeleteContext(session string) error {
	return c.deleteSessionAndCleanup(session)
}

// GetContext 获取指定会话的上下文信息
func (c *Controller) GetContext(session string) (CodeContext, error) {
	kernel := c.getJupyterKernel(session)
	if kernel == nil {
		return CodeContext{}, ErrContextNotFound
	}
	return CodeContext{
		ID:       session,
		Language: kernel.language,
	}, nil
}

// ListContext 列出指定语言的所有上下文
func (c *Controller) ListContext(language string) ([]CodeContext, error) {
	switch language {
	case Command.String(), BackgroundCommand.String(), SQL.String():
		return nil, fmt.Errorf("unsupported language context operation: %s", language)
	case "":
		return c.listAllContexts()
	default:
		return c.listLanguageContexts(Language(language))
	}
}

// DeleteLanguageContext 删除指定语言的所有上下文
func (c *Controller) DeleteLanguageContext(language Language) error {
	contexts, err := c.listLanguageContexts(language)
	if err != nil {
		return err
	}

	seen := make(map[string]struct{})
	for _, context := range contexts {
		if _, ok := seen[context.ID]; ok {
			continue
		}
		seen[context.ID] = struct{}{}

		if err := c.deleteSessionAndCleanup(context.ID); err != nil {
			return fmt.Errorf("error deleting context %s: %w", context.ID, err)
		}
	}
	return nil
}

// deleteSessionAndCleanup 删除会话并清理相关资源
func (c *Controller) deleteSessionAndCleanup(session string) error {
	if c.getJupyterKernel(session) == nil {
		return ErrContextNotFound
	}
	if err := c.jupyterClient().DeleteSession(session); err != nil {
		return err
	}
	c.jupyterClientMap.Delete(session)
	c.deleteDefaultSessionByID(session)
	return nil
}

// newContextID 生成新的上下文 ID
func (c *Controller) newContextID() string {
	return strings.ReplaceAll(uuid.New().String(), "-", "")
}

// newIpynbPath 创建新的 notebook 文件路径
func (c *Controller) newIpynbPath(sessionID, cwd string) (string, error) {
	if cwd != "" {
		err := os.MkdirAll(cwd, os.ModePerm)
		if err != nil {
			return "", err
		}
	}
	return filepath.Join(cwd, fmt.Sprintf("%s.ipynb", sessionID)), nil
}

// createDefaultLanguageJupyterContext 为无状态执行预热默认语言会话
func (c *Controller) createDefaultLanguageJupyterContext(language Language) error {
	if c.getDefaultLanguageSession(language) != "" {
		return nil
	}

	var (
		client  *jupyter.Client
		session *jupytersession.Session
		err     error
	)
	err = retry.OnError(kernelWaitingBackoff, func(err error) bool {
		log.Error("failed to create context, retrying: %v", err)
		return err != nil
	}, func() error {
		client, session, err = c.createJupyterContext(CreateContextRequest{
			Language: language,
			Cwd:      "",
		})
		return err
	})
	if err != nil {
		return err
	}

	c.setDefaultLanguageSession(language, session.ID)
	c.jupyterClientMap.Store(session.ID, &jupyterKernel{
		kernelID: session.Kernel.ID,
		client:   client,
		language: language,
	})
	return nil
}

// createJupyterContext 执行实际的上下文创建流程
func (c *Controller) createJupyterContext(request CreateContextRequest) (*jupyter.Client, *jupytersession.Session, error) {
	client := c.jupyterClient()

	kernel, err := c.searchKernel(client, request.Language)
	if err != nil {
		return nil, nil, err
	}

	sessionID := c.newContextID()
	ipynb, err := c.newIpynbPath(sessionID, request.Cwd)
	if err != nil {
		return nil, nil, err
	}

	jupyterSession, err := client.CreateSession(sessionID, ipynb, kernel)
	if err != nil {
		return nil, nil, err
	}

	kernels, err := client.ListKernels()
	if err != nil {
		return nil, nil, err
	}

	found := false
	for _, k := range kernels {
		if k.ID == jupyterSession.Kernel.ID {
			found = true
			break
		}
	}
	if !found {
		return nil, nil, errors.New("kernel not found")
	}

	return client, jupyterSession, nil
}

// storeJupyterKernel 缓存会话到内核的映射
func (c *Controller) storeJupyterKernel(sessionID string, kernel *jupyterKernel) {
	c.jupyterClientMap.Store(sessionID, kernel)
}

// jupyterClient 创建带认证的 Jupyter 客户端
func (c *Controller) jupyterClient() *jupyter.Client {
	httpClient := &http.Client{
		Transport: &jupyter.AuthTransport{
			Token: c.token,
			Base:  http.DefaultTransport,
		},
	}
	return jupyter.NewClient(c.baseURL,
		jupyter.WithToken(c.token),
		jupyter.WithHTTPClient(httpClient))
}

// getDefaultLanguageSession 获取指定语言的默认会话 ID
func (c *Controller) getDefaultLanguageSession(language Language) string {
	if v, ok := c.defaultLanguageSessions.Load(language); ok {
		if session, ok := v.(string); ok {
			return session
		}
	}
	return ""
}

// setDefaultLanguageSession 设置指定语言的默认会话 ID
func (c *Controller) setDefaultLanguageSession(language Language, sessionID string) {
	c.defaultLanguageSessions.Store(language, sessionID)
}

// deleteDefaultSessionByID 根据会话 ID 删除默认会话记录
func (c *Controller) deleteDefaultSessionByID(sessionID string) {
	c.defaultLanguageSessions.Range(func(key, value any) bool {
		if s, ok := value.(string); ok && s == sessionID {
			c.defaultLanguageSessions.Delete(key)
		}
		return true
	})
}

// listAllContexts 列出所有上下文
func (c *Controller) listAllContexts() ([]CodeContext, error) {
	contexts := make([]CodeContext, 0)
	c.jupyterClientMap.Range(func(key, value any) bool {
		session, _ := key.(string)
		if kernel, ok := value.(*jupyterKernel); ok && kernel != nil {
			contexts = append(contexts, CodeContext{ID: session, Language: kernel.language})
		}
		return true
	})

	c.defaultLanguageSessions.Range(func(key, value any) bool {
		lang, _ := key.(Language)
		session, _ := value.(string)
		if session == "" {
			return true
		}
		contexts = append(contexts, CodeContext{ID: session, Language: lang})
		return true
	})

	return contexts, nil
}

// listLanguageContexts 列出指定语言的所有上下文
func (c *Controller) listLanguageContexts(language Language) ([]CodeContext, error) {
	contexts := make([]CodeContext, 0)
	c.jupyterClientMap.Range(func(key, value any) bool {
		session, _ := key.(string)
		if kernel, ok := value.(*jupyterKernel); ok && kernel != nil && kernel.language == language {
			contexts = append(contexts, CodeContext{ID: session, Language: language})
		}
		return true
	})

	if defaultContext := c.getDefaultLanguageSession(language); defaultContext != "" {
		contexts = append(contexts, CodeContext{ID: defaultContext, Language: language})
	}

	return contexts, nil
}
