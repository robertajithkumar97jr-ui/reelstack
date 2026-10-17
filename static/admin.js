(() => {
  const rows = document.getElementById("rows");
  const count = document.getElementById("count");
  const search = document.getElementById("search");
  const fmt = (n) => n < 1048576 ? (n / 1024).toFixed(0) + " KB" : (n / 1048576).toFixed(1) + " MB";

  function cell(text) { const td = document.createElement("td"); td.textContent = text; return td; }

  async function load() {
    const res = await fetch("/api/admin/files?q=" + encodeURIComponent(search.value));
    const items = await res.json();
    count.textContent = items.length + (items.length === 1 ? " file" : " files");
    rows.innerHTML = "";
    items.forEach(it => {
      const tr = document.createElement("tr");
      tr.append(cell(it.student_name), cell(it.student_id), cell(it.course || ""));
      const file = document.createElement("td");
      const a = document.createElement("a");
      a.href = "/admin/download/" + it.id; a.textContent = it.original_name;
      file.append(a);
      tr.append(file, cell(fmt(it.size_bytes)), cell(new Date(it.uploaded_at).toLocaleString()));
      const act = document.createElement("td");
      const del = document.createElement("button");
      del.textContent = "Delete";
      del.onclick = async () => {
        if (!confirm("Delete " + it.original_name + "?")) return;
        await fetch("/api/admin/files/" + it.id, { method: "DELETE" });
        load();
      };
      act.append(del); tr.append(act); rows.append(tr);
    });
  }
  let t; search.oninput = () => { clearTimeout(t); t = setTimeout(load, 250); };
  load();
})();
