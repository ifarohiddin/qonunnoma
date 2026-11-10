/* Ilovani telefonga o'rnatish: service worker + "Bosh ekranga qo'shish" taklifi.
   Android (Chrome/Edge): brauzerning o'rnatish oynasi; iPhone/iPad (Safari): qo'lda qo'shish ko'rsatmasi. */
(function () {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () { navigator.serviceWorker.register('/sw.js').catch(function () {}); });
  }
  var standalone = (window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true;
  if (standalone) return;

  var KEY = 'qn-install-dismissed';
  function dismissed() { try { return Number(localStorage.getItem(KEY)) > Date.now() - 14 * 864e5; } catch (e) { return false; } }
  function remember() { try { localStorage.setItem(KEY, String(Date.now())); } catch (e) {} }

  var ua = navigator.userAgent || '';
  var ios = /iphone|ipad|ipod/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var deferred = null, box = null;

  function close() { if (box) { box.remove(); box = null; } }

  function show(kind) {
    if (box || dismissed()) return;
    box = document.createElement('div');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-label', 'Ilovani o‘rnatish');
    box.style.cssText = 'position:fixed;left:12px;right:12px;bottom:calc(12px + env(safe-area-inset-bottom,0px));z-index:2147483000;' +
      'max-width:460px;margin:0 auto;display:flex;gap:12px;align-items:center;padding:12px 14px;border-radius:16px;' +
      'background:#2B241D;color:#F7F2EC;box-shadow:0 10px 30px rgba(0,0,0,.35);font:500 14px/1.4 Manrope,system-ui,-apple-system,"Segoe UI",sans-serif;';
    var img = document.createElement('img');
    img.src = '/static/icon-192.png'; img.alt = ''; img.width = 40; img.height = 40;
    img.style.cssText = 'border-radius:10px;flex:none';
    var text = document.createElement('div');
    text.style.cssText = 'flex:1;min-width:0';
    var title = document.createElement('strong');
    title.textContent = 'Qonunnoma ilovasi';
    title.style.display = 'block';
    var sub = document.createElement('span');
    sub.style.cssText = 'opacity:.85;font-size:13px';
    sub.textContent = kind === 'ios'
      ? 'Safari’da pastdagi «Ulashish» tugmasini bosing, so‘ng «Bosh ekranga qo‘shish» ni tanlang.'
      : 'Bosh ekranga qo‘shing: tezroq ochiladi va to‘liq ekranda ishlaydi.';
    text.appendChild(title); text.appendChild(sub);
    box.appendChild(img); box.appendChild(text);

    if (kind === 'android') {
      var add = document.createElement('button');
      add.type = 'button'; add.textContent = 'O‘rnatish';
      add.style.cssText = 'flex:none;border:0;border-radius:999px;padding:9px 16px;background:#F7F2EC;color:#2B241D;font:700 14px Manrope,system-ui,sans-serif;cursor:pointer';
      add.onclick = function () {
        if (!deferred) return close();
        deferred.prompt();
        deferred.userChoice.then(function () { deferred = null; close(); remember(); });
      };
      box.appendChild(add);
    }
    var no = document.createElement('button');
    no.type = 'button'; no.setAttribute('aria-label', 'Yopish'); no.textContent = '×';
    no.style.cssText = 'flex:none;border:0;background:none;color:inherit;font-size:22px;line-height:1;padding:4px 6px;cursor:pointer;opacity:.8';
    no.onclick = function () { remember(); close(); };
    box.appendChild(no);
    document.body.appendChild(box);
  }

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault(); deferred = e;
    setTimeout(function () { show('android'); }, 4000);
  });
  window.addEventListener('appinstalled', function () { deferred = null; remember(); close(); });

  if (ios) {
    window.addEventListener('load', function () { setTimeout(function () { show('ios'); }, 4000); });
  }
})();
