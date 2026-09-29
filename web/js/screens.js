/** Два экрана сайта с адресуемыми разделами внутри сквозного маршрута. */
export function initScreens() {
  const verification = document.querySelector("#verification-screen");
  const route = document.querySelector("#route-screen");
  const verifyLink = document.querySelector("#nav-verification");
  const routeLink = document.querySelector("#nav-route");

  function select() {
    const id = decodeURIComponent(location.hash.slice(1));
    const target = id ? document.getElementById(id) : null;
    const showRoute = Boolean(target?.closest("#route-screen"));
    verification.hidden = showRoute;
    route.hidden = !showRoute;
    verifyLink.setAttribute("aria-current", showRoute ? "false" : "page");
    routeLink.setAttribute("aria-current", showRoute ? "page" : "false");
    if (target) requestAnimationFrame(() => target.scrollIntoView());
  }

  window.addEventListener("hashchange", select);
  select();
}
