"""Render the local worker inbox and operator traffic browser interface."""


def render_local_page(nonce: str) -> bytes:
    """Return the local page with transient credentials and safe text rendering."""
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>Ovue</title>
  <style nonce="{nonce}">
    :root {{ color-scheme: light dark; font: 16px system-ui, sans-serif; }}
    body {{ max-width: 58rem; margin: 2.5rem auto; padding: 0 1.25rem; }}
    h1 {{ margin-bottom: 0.4rem; }}
    .intro {{ color: #888; margin-top: 0; }}
    nav {{ display: flex; gap: 0.6rem; margin: 1.5rem 0; }}
    button, input {{ font: inherit; padding: 0.7rem; }}
    button {{ cursor: pointer; }}
    button:disabled {{ cursor: wait; opacity: 0.65; }}
    form {{ display: grid; gap: 0.7rem; max-width: 38rem; }}
    input {{ width: 100%; box-sizing: border-box; }}
    input[type="checkbox"] {{ width: auto; }}
    section[hidden], form[hidden] {{ display: none; }}
    .view {{ border-top: 1px solid #777; padding-top: 1.2rem; }}
    .toolbar {{ display: flex; align-items: center; gap: 0.8rem; }}
    .toolbar h2 {{ flex: 1; }}
    .record {{
      border: 1px solid #777; border-radius: 0.5rem; padding: 1rem;
      margin: 0.8rem 0;
    }}
    .record h3 {{ margin: 0 0 0.4rem; }}
    .record p {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
    .meta {{ color: #888; font-size: 0.9rem; }}
    #result {{ min-height: 1.5rem; }}
  </style>
</head>
<body>
  <main>
    <h1>Ovue</h1>
    <p class="intro">Pointer inbox and operator traffic</p>
    <nav aria-label="Ovue views">
      <button id="worker-tab" type="button">Worker inbox</button>
      <button id="operator-tab" type="button">Operator traffic</button>
    </nav>
    <p id="result" role="status" aria-live="polite"></p>
    <section id="worker-view" class="view">
      <h2>Worker inbox</h2>
      <form id="worker-form" autocomplete="off">
        <label for="token">Seat token</label>
        <input id="token" name="token" type="password"
          autocomplete="new-password" required>
        <button id="worker-connect" type="submit">Connect inbox</button>
      </form>
      <section id="worker-inbox" hidden>
        <div class="toolbar">
          <h2 id="worker-name"></h2>
          <button id="worker-refresh" type="button">Refresh inbox</button>
        </div>
        <p id="worker-seat"></p>
        <p>Acknowledge a pointer only after its work is complete or recorded as
          failed.
        </p>
        <label><input id="show-read" type="checkbox">
          Include acknowledged pointers
        </label>
        <div id="worker-items"></div>
        <button id="worker-older" type="button" hidden>Load older pointers</button>
      </section>
    </section>
    <section id="operator-view" class="view" hidden>
      <h2>Operator traffic</h2>
      <p>Read-only view of all pointers and each recipient's delivery state.</p>
      <form id="operator-form" autocomplete="off">
        <label for="operator-code">One-time code from the Ovue server terminal</label>
        <input id="operator-code" name="operator-code" type="password"
          autocomplete="new-password" required>
        <button id="operator-connect" type="submit">Open traffic view</button>
      </form>
      <section id="operator-traffic" hidden>
        <div class="toolbar">
          <h2>Recent traffic</h2>
          <button id="operator-refresh" type="button">Refresh traffic</button>
        </div>
        <div id="operator-items"></div>
        <button id="operator-older" type="button" hidden>Load older traffic</button>
      </section>
    </section>
  </main>
  <script nonce="{nonce}">
    const result = document.getElementById("result");
    const workerView = document.getElementById("worker-view");
    const operatorView = document.getElementById("operator-view");
    const workerTab = document.getElementById("worker-tab");
    const operatorTab = document.getElementById("operator-tab");
    const workerForm = document.getElementById("worker-form");
    const workerTokenInput = document.getElementById("token");
    const workerConnect = document.getElementById("worker-connect");
    const workerInbox = document.getElementById("worker-inbox");
    const workerItems = document.getElementById("worker-items");
    const workerOlder = document.getElementById("worker-older");
    const workerName = document.getElementById("worker-name");
    const workerSeat = document.getElementById("worker-seat");
    const showRead = document.getElementById("show-read");
    const operatorForm = document.getElementById("operator-form");
    const operatorCodeInput = document.getElementById("operator-code");
    const operatorConnect = document.getElementById("operator-connect");
    const operatorTraffic = document.getElementById("operator-traffic");
    const operatorItems = document.getElementById("operator-items");
    const operatorOlder = document.getElementById("operator-older");
    let workerAuthorization = "";
    let workerSeatId = "";
    let workerCursor = null;
    let operatorCursor = null;

    function showView(view) {{
      const isWorker = view === "worker";
      workerView.hidden = !isWorker;
      operatorView.hidden = isWorker;
      result.textContent = "";
    }}

    function addRecord(container, record, canAcknowledge) {{
      const card = document.createElement("article");
      card.className = "record";
      const title = document.createElement("h3");
      title.textContent = record.ref.title || record.kind;
      const sender = document.createElement("p");
      sender.className = "meta";
      sender.textContent =
        `From ${{record.from.display_name}} (${{record.from.role}}) → ${{record.to}}`;
      const description = document.createElement("p");
      description.textContent = record.description;
      const reference = document.createElement("code");
      reference.textContent = record.ref.url;
      const state = document.createElement("p");
      state.className = "meta";
      state.textContent =
        `${{record.kind}} · ${{record.state}} · ${{record.created_at}}`;
      card.append(title, sender, description, reference, state);
      if (canAcknowledge && record.state === "unread") {{
        const acknowledge = document.createElement("button");
        acknowledge.type = "button";
        acknowledge.textContent = "Acknowledge";
        acknowledge.addEventListener("click", async () => {{
          acknowledge.disabled = true;
          try {{
            const path = `/ack/${{encodeURIComponent(record.delivery_id)}}`;
            const response = await fetch(path, {{
              method: "POST",
              headers: {{ Authorization: workerAuthorization }},
              cache: "no-store",
              credentials: "omit",
              redirect: "error",
              referrerPolicy: "no-referrer"
            }});
            if (!response.ok) throw new Error("acknowledgement failed");
            result.textContent = "Pointer acknowledged.";
            await refreshWorkerInbox();
          }} catch {{
            result.textContent = "Could not acknowledge this pointer.";
            acknowledge.disabled = false;
          }}
        }});
        card.append(acknowledge);
      }}
      container.append(card);
    }}

    async function loadWorkerInbox(reset) {{
      if (!workerAuthorization || !workerSeatId) return;
      if (reset) {{
        workerCursor = null;
        workerItems.replaceChildren();
      }}
      result.textContent = "Loading inbox…";
      try {{
        const query = new URLSearchParams({{ limit: "100" }});
        if (!showRead.checked) query.set("unread", "1");
        if (workerCursor) query.set("cursor", workerCursor);
        const path =
          `/inbox/${{encodeURIComponent(workerSeatId)}}?${{query}}`;
        const response = await fetch(path, {{
            headers: {{ Authorization: workerAuthorization }},
            cache: "no-store",
            credentials: "omit",
            redirect: "error",
            referrerPolicy: "no-referrer"
        }});
        if (!response.ok) throw new Error("inbox unavailable");
        const page = await response.json();
        for (const record of page.items) addRecord(workerItems, record, true);
        workerCursor = page.next_cursor;
        workerOlder.hidden = !workerCursor;
        result.textContent = `${{page.items.length}} pointer(s) loaded.`;
      }} catch {{
        result.textContent = "Could not load the inbox. Reconnect with the seat token.";
        workerForm.hidden = false;
        workerInbox.hidden = true;
        workerOlder.hidden = true;
        workerAuthorization = "";
        workerCursor = null;
        workerSeatId = "";
      }}
    }}

    function refreshWorkerInbox() {{
      return loadWorkerInbox(true);
    }}

    async function loadOperatorTraffic(reset) {{
      if (reset) {{
        operatorCursor = null;
        operatorItems.replaceChildren();
      }}
      result.textContent = "Loading traffic…";
      try {{
        const query = new URLSearchParams({{ limit: "100" }});
        if (operatorCursor) query.set("cursor", operatorCursor);
        const response = await fetch(`/operator/traffic?${{query}}`, {{
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          referrerPolicy: "no-referrer"
        }});
        if (!response.ok) throw new Error("traffic unavailable");
        const page = await response.json();
        for (const record of page.items) addRecord(operatorItems, record, false);
        operatorCursor = page.next_cursor;
        operatorOlder.hidden = !operatorCursor;
        result.textContent =
          `${{page.items.length}} recent pointer delivery record(s).`;
      }} catch {{
        result.textContent = "The operator session expired. Reconnect with a new code.";
        operatorForm.hidden = false;
        operatorTraffic.hidden = true;
        operatorOlder.hidden = true;
      }}
    }}

    function refreshOperatorTraffic() {{
      return loadOperatorTraffic(true);
    }}

    workerTab.addEventListener("click", () => showView("worker"));
    operatorTab.addEventListener("click", () => showView("operator"));
    document.getElementById("worker-refresh")
      .addEventListener("click", refreshWorkerInbox);
    workerOlder.addEventListener("click", () => loadWorkerInbox(false));
    showRead.addEventListener("change", refreshWorkerInbox);
    document.getElementById("operator-refresh")
      .addEventListener("click", refreshOperatorTraffic);
    operatorOlder.addEventListener("click", () => loadOperatorTraffic(false));

    workerForm.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const token = workerTokenInput.value;
      workerTokenInput.value = "";
      workerConnect.disabled = true;
      workerAuthorization = `Bearer ${{token}}`;
      try {{
        const response = await fetch("/me", {{
          headers: {{ Authorization: workerAuthorization }},
          cache: "no-store",
          credentials: "omit",
          redirect: "error",
          referrerPolicy: "no-referrer"
        }});
        if (!response.ok) throw new Error("seat token rejected");
        const seat = await response.json();
        workerSeatId = seat.id;
        workerName.textContent = `${{seat.display_name}} (@${{seat.handle}})`;
        workerSeat.textContent = `Seat ${{seat.id}} · ${{seat.role}}`;
        workerForm.hidden = true;
        workerInbox.hidden = false;
        await refreshWorkerInbox();
      }} catch {{
        workerAuthorization = "";
        result.textContent =
          "That token was not accepted or Ovue could not be reached.";
      }} finally {{
        workerTokenInput.value = "";
        workerConnect.disabled = false;
      }}
    }});

    operatorForm.addEventListener("submit", async (event) => {{
      event.preventDefault();
      const code = operatorCodeInput.value;
      operatorCodeInput.value = "";
      operatorConnect.disabled = true;
      try {{
        const response = await fetch("/operator/session", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ code }}),
          cache: "no-store",
          credentials: "same-origin",
          redirect: "error",
          referrerPolicy: "no-referrer"
        }});
        if (!response.ok) throw new Error("operator code rejected");
        await response.json();
        operatorForm.hidden = true;
        operatorTraffic.hidden = false;
        await refreshOperatorTraffic();
      }} catch {{
        result.textContent = "That code was not accepted or has expired.";
      }} finally {{
        operatorCodeInput.value = "";
        operatorConnect.disabled = false;
      }}
    }});
  </script>
</body>
</html>
"""
    return page.encode("utf-8")
