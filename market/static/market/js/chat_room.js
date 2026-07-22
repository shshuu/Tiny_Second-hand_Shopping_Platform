(() => {
  const list = document.getElementById("chat-messages");
  const form = document.getElementById("chat-form");
  const status = document.getElementById("chat-status");
  if (!list || !form || !status || !list.dataset.chatSocket) return;
  const input = form.querySelector("[name=content]");
  let socket;
  let retryTimer;
  const connect = () => {
    socket = new WebSocket(list.dataset.chatSocket);
    socket.onopen = () => { status.textContent = "실시간 연결됨"; };
    socket.onclose = () => {
      status.textContent = "연결이 끊겼습니다. 잠시 후 다시 연결합니다.";
      retryTimer = window.setTimeout(connect, 2000);
    };
    socket.onerror = () => socket.close();
    socket.onmessage = (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch (_) { return; }
      if (data.error) { status.textContent = "메시지를 전송할 수 없습니다."; return; }
      const line = document.createElement("p");
      const name = document.createElement("strong");
      name.textContent = data.sender;
      line.append(name, `: ${data.content}`);
      list.append(line);
    };
  };
  form.addEventListener("submit", (event) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      event.preventDefault();
      socket.send(JSON.stringify({content: input.value}));
      input.value = "";
    }
  });
  window.addEventListener("beforeunload", () => window.clearTimeout(retryTimer));
  connect();
})();
