// serve-dist.cjs —— 极简静态服务：node scripts/serve-dist.cjs [端口，默认 4380]
// 只绑 127.0.0.1，只读 dist/。端口被占用时请换 4381–4389，不要用 8801。
const http = require('http')
const fs = require('fs')
const path = require('path')
const root = path.resolve(__dirname, '..', 'dist')
const port = Number(process.argv[2] || process.env.PORT || 4380)
const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.zip': 'application/zip', '.svg': 'image/svg+xml' }
http.createServer((req, res) => {
  let p = decodeURIComponent(new URL(req.url, 'http://x').pathname)
  let f = path.normalize(path.join(root, p))
  if (!f.startsWith(root)) { res.writeHead(403); return res.end('forbidden') }
  if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html')
  fs.readFile(f, (err, buf) => {
    if (err) { res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' }); return res.end('404') }
    res.writeHead(200, { 'content-type': types[path.extname(f)] || 'application/octet-stream' })
    res.end(buf)
  })
}).listen(port, '127.0.0.1', () => console.log(`serving dist/ at http://127.0.0.1:${port}/`))
