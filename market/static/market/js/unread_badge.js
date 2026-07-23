(() => {
  const badge = document.getElementById("unread-badge");
  if (!badge) return;
  const update = (value) => {
    const count = Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
    badge.hidden = count === 0;
    badge.textContent = count > 99 ? "99+" : String(count);
  };
  const updateRooms = (rooms) => {
    const values = rooms || {};
    document.querySelectorAll("[data-room-unread]").forEach((badge) => {
      const count = Number(values[badge.dataset.roomUnread] || 0);
      badge.hidden = count <= 0;
      badge.textContent = count > 99 ? "99+" : String(Math.max(0, count));
    });
  };
  const activeRoom = (roomId) => {
    const room = document.querySelector("[data-chat-room-id]");
    return room && room.dataset.chatRoomId === roomId && document.visibilityState === "visible" && document.hasFocus() && window.tinyChatSocketOpen === true;
  };
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  let retryTimer;
  const connect = () => {
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/unread/`);
    socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.room_id && activeRoom(data.room_id)) {
          window.dispatchEvent(new CustomEvent("tiny-chat-mark-read"));
          return;
        }
        update(data.total_unread ?? data.unread_count);
        updateRooms(data.unread_rooms);
      } catch (_) { /* invalid events are ignored */ }
    };
    socket.onclose = () => { retryTimer = window.setTimeout(connect, 2000); };
    socket.onerror = () => socket.close();
  };
  window.addEventListener("beforeunload", () => window.clearTimeout(retryTimer));
  connect();
})();
