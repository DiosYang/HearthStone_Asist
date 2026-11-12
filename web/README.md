# 网页客户端

纯HTML/CSS/JavaScript，不依赖Node构建或外部CDN。FastAPI在同一地址提供网页和API，网页不持有模型Key，也不直连DeepSeek。

- index.html：三栏布局、注册/登录、偏好表单。
- style.css：桌面/手机布局、键盘焦点和减少动画支持。
- app.js：会话、历史、偏好、fetch流式交互、停止、真实观测。
- sse.js：跨chunk的UTF8/SSE解析。
- sse.test.js：真实ReadableStream的协议单元检查。

不要直接双击HTML或仅运行静态服务器：必须启动项目FastAPI，浏览器访问同源地址。密码不存localStorage，认证使用HttpOnly Cookie；localStorage仅存按用户分区的最近会话ID。模型回复作为纯文本渲染，不执行HTML/脚本，也不加载模型给出的远程图片。

在本目录有Node时可运行 `node --test sse.test.js`，无需npm install。接口说明与启动命令见项目根README。
