(() => {
  const badge = document.getElementById("unread-badge");
  if (!badge) return;
  const update = (value) => {
    const count = Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
    badge.hidden = count === 0;
    badge.textContent = count > 99 ? "99+" : String(count);
  };
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  let retryTimer;
  const connect = () => {
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/unread/`);
    socket.onmessage = (event) => {
      try { update(JSON.parse(event.data).unread_count); } catch (_) { /* invalid events are ignored */ }
    };
    socket.onclose = () => { retryTimer = window.setTimeout(connect, 2000); };
    socket.onerror = () => socket.close();
  };
  window.addEventListener("beforeunload", () => window.clearTimeout(retryTimer));
  connect();
})();
