from pathlib import Path
import subprocess

auth_root = Path("auth_info")
if (auth_root / "creds.json").exists():
    auth_dir = auth_root
else:
    candidates = [p for p in auth_root.iterdir() if p.is_dir() and (p / "creds.json").exists()]
    if not candidates:
        raise SystemExit("auth_info में creds.json नहीं मिला।")
    auth_dir = candidates[0]

script = Path(".temp_list_groups.mjs")
script.write_text(f'''
import makeWASocket, {{ useMultiFileAuthState }} from "@whiskeysockets/baileys";
import P from "pino";

const {{ state, saveCreds }} = await useMultiFileAuthState({str(auth_dir.resolve())!r});
const sock = makeWASocket({{
  auth: state,
  logger: P({{ level: "silent" }}),
  syncFullHistory: false
}});

sock.ev.on("creds.update", saveCreds);

sock.ev.on("connection.update", async (update) => {{
  if (update.connection !== "open") return;
  try {{
    const groups = await sock.groupFetchAllParticipating();
    console.log("\\n--- GROUP NAME = GROUP ID ---");
    for (const [id, group] of Object.entries(groups)) {{
      console.log(`${{group.subject || "NO_NAME"}} = ${{id}}`);
    }}
  }} catch (error) {{
    console.error("Error:", error.message);
  }} finally {{
    sock.end(new Error("Completed"));
    process.exit(0);
  }}
}});
''')

try:
    subprocess.run(["node", str(script)], check=False)
finally:
    script.unlink(missing_ok=True)