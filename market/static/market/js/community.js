(() => {
  const list=document.getElementById("community-messages"), form=document.getElementById("community-form");
  if(!list) return;
  const status=document.getElementById("community-status"), input=form?.querySelector("[name=content]"), button=form?.querySelector("button");
  const accountCanSend=list.dataset.canSend === "true";
  let socket, retryTimer;
  const updateComposerState=()=>{
    const socketReady=Boolean(socket && socket.readyState===WebSocket.OPEN);
    if(input) input.disabled=!accountCanSend;
    if(button) button.disabled=!accountCanSend || !socketReady;
  };
  const render=(data)=>{
    const p=document.createElement("p"), strong=document.createElement("strong");
    strong.textContent=data.sender || "사용자"; p.append(strong, " · ");
    const time=document.createElement("time"); time.textContent=data.created_at ? new Date(data.created_at).toLocaleString() : ""; p.append(time, ": ", data.content || "");
    if(list.dataset.canReport === "1" && String(data.sender_id) !== list.dataset.currentUser && data.id){
      const link=document.createElement("a"); link.href=`${list.dataset.reportPrefix}${data.id}/`; link.textContent=" 신고"; p.append(link);
    }
    list.append(p);
  };
  const connect=()=>{
    if(socket && (socket.readyState===WebSocket.OPEN || socket.readyState===WebSocket.CONNECTING)) return;
    clearTimeout(retryTimer); updateComposerState(); status.textContent="실시간 연결 중";
    socket=new WebSocket(list.dataset.communitySocket);
    updateComposerState();
    socket.onopen=()=>{ status.textContent="실시간 연결됨"; updateComposerState(); };
    socket.onclose=()=>{ status.textContent="연결이 끊겼습니다. 재연결합니다."; updateComposerState(); if(!retryTimer) retryTimer=setTimeout(()=>{retryTimer=null; connect();},2000); };
    socket.onerror=()=>socket.close();
    socket.onmessage=(event)=>{ try { const data=JSON.parse(event.data); if(data.error){status.textContent="메시지를 전송할 수 없습니다."; return;} render(data); } catch(_){} };
  };
  if(form) form.addEventListener("submit",(event)=>{ event.preventDefault(); if(!accountCanSend || socket?.readyState!==WebSocket.OPEN) return; socket.send(JSON.stringify({content:input.value})); input.value=""; });
  addEventListener("beforeunload",()=>clearTimeout(retryTimer)); updateComposerState(); connect();
})();
