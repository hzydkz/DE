// 분야 탭: JS가 없으면 모든 분야가 세로로 이어서 보인다.
(function () {
  var tabs = document.querySelectorAll(".tabs a[data-tab]");
  var panels = document.querySelectorAll("[data-panel]");
  if (!tabs.length) return;
  document.documentElement.classList.add("js");
  function show(key) {
    var found = false;
    panels.forEach(function (p) { var on = p.dataset.panel === key; p.hidden = !on; found = found || on; });
    if (!found) return show(tabs[0].dataset.tab);
    tabs.forEach(function (t) { t.classList.toggle("on", t.dataset.tab === key); });
  }
  tabs.forEach(function (t) {
    t.addEventListener("click", function (e) {
      e.preventDefault();
      show(t.dataset.tab);
      history.replaceState(null, "", "#" + t.dataset.tab);
      window.scrollTo({ top: 0 });
    });
  });
  show(location.hash.slice(1) || tabs[0].dataset.tab);
  // 해시로 들어오면 브라우저가 섹션으로 스크롤해 날짜·탭이 가려지므로 맨 위로
  if (location.hash) window.addEventListener("load", function () { window.scrollTo(0, 0); });
})();
