(() => {
  const form = document.getElementById("upload-form");
  const drop = document.getElementById("drop");
  const input = document.getElementById("files");
  const list = document.getElementById("file-list");
  const msg = document.getElementById("message");
  const bar = document.getElementById("progress");
  const send = document.getElementById("send");
  let files = [];

  const fmt = (n) => n < 1048576 ? (n / 1024).toFixed(0) + " KB" : (n / 1048576).toFixed(1) + " MB";
  const say = (text, kind = "") => { msg.textContent = text; msg.className = "message " + kind; };

  function render() {
    list.innerHTML = "";
    files.forEach((f, i) => {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = `${f.name} (${fmt(f.size)})`;
      const rm = document.createElement("button");
      rm.type = "button"; rm.textContent = "Remove";
      rm.onclick = () => { files.splice(i, 1); render(); };
      li.append(label, rm);
      list.append(li);
    });
  }
  function add(newFiles) { files = files.concat(Array.from(newFiles)); render(); say(""); }

  drop.onclick = () => input.click();
  drop.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } };
  input.onchange = () => { add(input.files); input.value = ""; };
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => add(e.dataTransfer.files));

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = new FormData(form);
    data.delete("files");
    files.forEach(f => data.append("files", f));
    if (!files.length) { say("Choose at least one file.", "error"); return; }

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) bar.firstElementChild.style.width = (ev.loaded / ev.total * 100) + "%";
    };
    xhr.onloadstart = () => { send.disabled = true; bar.hidden = false; say("Sending..."); };
    xhr.onloadend = () => {
      send.disabled = false; bar.hidden = true; bar.firstElementChild.style.width = "0";
      let res = {};
      try { res = JSON.parse(xhr.responseText); } catch (_) {}
      if (xhr.status === 200 && res.ok) {
        say(`Sent ${res.saved.length} file${res.saved.length > 1 ? "s" : ""}. You can close this page.`, "ok");
        files = []; render(); form.reset();
      } else {
        say((res.errors || ["Upload failed. Check your connection and try again."]).join(" "), "error");
      }
    };
    xhr.send(data);
  });
})();
