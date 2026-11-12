# 项目页部署

项目主页：[egolens.top](https://egolens.top/)。

`site/`包含项目介绍、代码链接和预录演示，可部署到静态托管服务。

## 公开静态站点

将`site/`目录部署到GitHub Pages等静态托管服务。`site/assets/demos/`保存演示媒体。

本仓库使用`gh-pages`分支的根目录托管静态文件。提交并推送`main`后，运行：

```bash
node tools/publish-pages.mjs
```

发布脚本将当前提交的`site/`文件树同步到`gh-pages`。

## 域名

项目使用`egolens.top`作为自定义域名。域名配置保存在`site/CNAME`，站点使用HTTPS访问。

## 其他托管方式

使用独立Web主机时，可参考`deploy/Caddyfile.example`配置静态目录。运行环境和数据格式分别见[环境说明](ENVIRONMENTS.md)与[数据说明](DATA.md)。
