/* 站点脚本：代码复制、本页目录高亮、窄屏默认收起章目录。无外部依赖，file:// 下可用。 */
(function () {
  'use strict'

  // 复制代码（file:// 不是安全上下文，navigator.clipboard 可能不存在，退回 execCommand）
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text)
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea')
      ta.value = text
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      var ok = false
      try { ok = document.execCommand('copy') } catch (e) { ok = false }
      document.body.removeChild(ta)
      ok ? resolve() : reject(new Error('copy failed'))
    })
  }
  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest && ev.target.closest('button.copy')
    if (!btn) return
    var pre = btn.closest('.code').querySelector('pre')
    copyText(pre.textContent.replace(/\n$/, '')).then(function () {
      btn.textContent = '已复制'
      btn.classList.add('done')
      setTimeout(function () { btn.textContent = '复制'; btn.classList.remove('done') }, 1500)
    }, function () {
      btn.textContent = '请手动复制'
      setTimeout(function () { btn.textContent = '复制' }, 1800)
    })
  })

  // 本页目录：滚动高亮
  var toc = document.querySelector('.toc')
  if (toc && 'IntersectionObserver' in window) {
    var links = {}
    toc.querySelectorAll('a[href^="#"]').forEach(function (a) { links[decodeURIComponent(a.getAttribute('href').slice(1))] = a })
    var heads = Object.keys(links).map(function (id) { return document.getElementById(id) }).filter(Boolean)
    var current = null
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          if (current) current.classList.remove('on')
          current = links[e.target.id]
          if (current) {
            current.classList.add('on')
            var box = toc.querySelector('.toc-in') || toc
            var top = current.offsetTop
            if (top < toc.scrollTop || top > toc.scrollTop + toc.clientHeight - 40) toc.scrollTop = top - 80
          }
        }
      })
    }, { rootMargin: '-72px 0px -70% 0px', threshold: 0 })
    heads.forEach(function (h) { io.observe(h) })
  }

  // 窄屏：章目录默认收起
  var side = document.querySelector('.side-d')
  if (side && window.matchMedia('(max-width: 860px)').matches) side.removeAttribute('open')
})()
