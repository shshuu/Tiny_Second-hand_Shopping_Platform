(() => {
  const list=document.getElementById("community-messages"), form=document.getElementById("community-form");
  if(!list) return;
  const status=document.getElementById("community-status"), input=form?.querySelector("[name=content]"), button=form?.querySelector("button");
  let socket, retryTimer;
  const enabled=(value)=>{ if(input) input.disabled=!value; if(button) button.disabled=!value; };
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
    socket=new WebSocket(list.dataset.communitySocket);
    socket.onopen=()=>{ status.textContent="실시간 연결됨"; enabled(true); };
    socket.onclose=()=>{ enabled(false); status.textContent="연결이 끊겼습니다. 재연결합니다."; clearTimeout(retryTimer); retryTimer=setTimeout(connect,2000); };
    socket.onerror=()=>socket.close();
    socket.onmessage=(event)=>{ try { const data=JSON.parse(event.data); if(data.error){status.textContent="메시지를 전송할 수 없습니다."; return;} render(data); } catch(_){} };
  };
  if(form) form.addEventListener("submit",(event)=>{ event.preventDefault(); if(socket?.readyState!==WebSocket.OPEN) return; socket.send(JSON.stringify({content:input.value})); input.value=""; });
  addEventListener("beforeunload",()=>clearTimeout(retryTimer)); connect();
})();
