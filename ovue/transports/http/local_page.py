"""Render the local browser page used to verify a seat token."""


def render_local_connection_page(nonce: str) -> bytes:
    """Return a static same-origin token check page with nonce-protected assets."""
    page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>Ovue local connection check</title>
  <style nonce="{nonce}">
    :root {{ color-scheme: light dark; font: 16px system-ui, sans-serif; }}
    body {{ max-width: 34rem; margin: 4rem auto; padding: 0 1.25rem; }}
    form {{ display: grid; gap: 0.75rem; margin-top: 1.5rem; }}
    input, button {{ font: inherit; padding: 0.7rem; }}
    #result {{ min-height: 1.5rem; }}
  </style>
</head>
<body>
  <main>
    <h1>Connect to Ovue</h1>
    <p>Enter a seat token to check that Ovue is running and accepts it.</p>
    <form id="token-form" autocomplete="off">
      <label for="token">Seat token</label>
      <input id="token" name="token" type="password"
        autocomplete="new-password" required>
      <button id="submit" type="submit">Check connection</button>
    </form>
    <p id="result" role="status" aria-live="polite"></p>
  </main>
  <script nonce="{nonce}">
    const form = document.getElementById("token-form");
    const tokenInput = document.getElementById("token");
    const submitButton = document.getElementById("submit");
    const result = document.getElementById("result");

    form.addEventListener("submit", async (event) => {{
      event.preventDefault();
      let token = tokenInput.value;
      tokenInput.value = "";
      submitButton.disabled = true;
      result.textContent = "Checking connection…";
      const headers = new Headers({{ Authorization: `Bearer ${{token}}` }});
      token = "";

      try {{
        const response = await fetch("/seats", {{
          method: "GET",
          headers,
          cache: "no-store",
          credentials: "omit",
          redirect: "error",
          referrerPolicy: "no-referrer"
        }});
        if (!response.ok) {{
          result.textContent = response.status === 401
            ? "That token was not accepted."
            : `Ovue returned HTTP ${{response.status}}.`;
          return;
        }}
        const directory = await response.json();
        const count = Array.isArray(directory.items) ? directory.items.length : 0;
        result.textContent = `Connected. Ovue returned ${{count}} seats.`;
      }} catch {{
        result.textContent =
          "Could not reach Ovue. Check that the local server is running.";
      }} finally {{
        headers.delete("Authorization");
        tokenInput.value = "";
        submitButton.disabled = false;
        tokenInput.focus();
      }}
    }});
  </script>
</body>
</html>
"""
    return page.encode("utf-8")
