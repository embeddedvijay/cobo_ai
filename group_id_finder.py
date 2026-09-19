#!/usr/bin/env python3
"""Reusable WhatsApp group-ID finder for any project that already uses Baileys.

The Python file asks for:
  1) Baileys project folder (must contain node_modules)
  2) auth folder (must contain creds.json)

It creates one temporary .mjs file inside that project, runs Node/Baileys,
prints "GROUP NAME = 1203...@g.us", then deletes the temporary file.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def ask_path(prompt: str, default: str = "") -> Path:
    answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip() or default
    return Path(os.path.expanduser(answer)).resolve()


project = ask_path("Baileys project folder", ".")
if not (project / "node_modules" / "@whiskeysockets" / "baileys").exists():
    print("Error: node_modules/@whiskeysockets/baileys not found in that folder.")
    print("Choose the project folder and run npm install there first.")
    sys.exit(1)

auth = ask_path("Baileys auth folder (contains creds.json)", str(project / "auth_info"))
if not (auth / "creds.json").exists():
    print(f"Warning: creds.json not found in {auth}")
    print("Baileys may show a QR login. Enter the exact auth subfolder if login already exists.")

node_code = r'''
import process from 'node:process';
import P from 'pino';
import qrcode from 'qrcode-terminal';
import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys';

const authDir = process.env.BAILEYS_AUTH_DIR;
const { state, saveCreds } = await useMultiFileAuthState(authDir);
const { version } = await fetchLatestBaileysVersion();
const sock = makeWASocket({
  version, auth: state, logger: P({ level: 'silent' }),
  markOnlineOnConnect: false, syncFullHistory: false,
});
sock.ev.on('creds.update', saveCreds);
sock.ev.on('connection.update', async ({ connection, qr, lastDisconnect }) => {
  if (qr) {
    console.log('\nScan QR with WhatsApp, then wait for the list.\n');
    qrcode.generate(qr, { small: true });
  }
  if (connection === 'open') {
    try {
      const groups = await sock.groupFetchAllParticipating();
      const rows = Object.values(groups)
        .map(group => ({ name: group.subject || '(no name)', jid: group.id }))
        .sort((a, b) => a.name.localeCompare(b.name));
      console.log('\n--- WHATSAPP GROUP IDs ---');
      for (const row of rows) console.log(`${row.name} = ${row.jid}`);
      if (!rows.length) console.log('No groups found for this account.');
    } catch (error) {
      console.error('Could not fetch groups:', error.message || error);
      process.exitCode = 1;
    } finally {
      setTimeout(() => process.exit(), 300);
    }
  }
  if (connection === 'close') {
    const code = lastDisconnect?.error?.output?.statusCode;
    console.error(code === DisconnectReason.loggedOut
      ? 'Logged out: delete only this auth folder and log in again.'
      : 'Connection closed before group list was fetched.');
    process.exit(1);
  }
});
'''

temp = project / ".group_id_finder_temp.mjs"
try:
    temp.write_text(textwrap.dedent(node_code), encoding="utf-8")
    env = {**os.environ, "BAILEYS_AUTH_DIR": str(auth)}
    subprocess.run(["node", temp.name], cwd=project, env=env, check=False)
finally:
    temp.unlink(missing_ok=True)
