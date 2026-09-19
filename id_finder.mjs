/**
 * Prints group display names and JIDs using an existing Baileys auth folder.
 *
 * Run: npm run groups
 * It asks for the auth path at runtime, so no config file is edited.
 */
import path from 'node:path';
import process from 'node:process';
import { createInterface } from 'node:readline/promises';
import P from 'pino';
import qrcode from 'qrcode-terminal';
import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys';

const readline = createInterface({ input: process.stdin, output: process.stdout });
const answer = await readline.question('Baileys auth folder path [./auth_info/dust]: ');
readline.close();

const authDir = path.resolve(process.cwd(), answer.trim() || './auth_info/dust');
console.log(`Using auth folder: ${authDir}`);

const { state, saveCreds } = await useMultiFileAuthState(authDir);
const { version } = await fetchLatestBaileysVersion();
const sock = makeWASocket({
  version,
  auth: state,
  logger: P({ level: 'silent' }),
  markOnlineOnConnect: false,
  syncFullHistory: false,
});

sock.ev.on('creds.update', saveCreds);
sock.ev.on('connection.update', async ({ connection, qr, lastDisconnect }) => {
  if (qr) {
    console.log('\nNo valid login found. Scan this QR once, then run the command again if needed.\n');
    qrcode.generate(qr, { small: true });
  }
  if (connection === 'open') {
    try {
      const groups = await sock.groupFetchAllParticipating();
      const rows = Object.values(groups)
        .map(group => ({ name: group.subject || '(no name)', jid: group.id }))
        .sort((a, b) => a.name.localeCompare(b.name));

      console.log('\n--- WHATSAPP GROUP IDs ---');
      if (!rows.length) console.log('No participating groups returned for this WhatsApp account.');
      for (const row of rows) console.log(`${row.name} = ${row.jid}`);
      console.log('\nCopy only the part after = into config when you want to use a direct JID.');
    } catch (error) {
      console.error('Unable to fetch groups:', error.message || error);
    } finally {
      setTimeout(() => process.exit(0), 300);
    }
  }
  if (connection === 'close') {
    const code = lastDisconnect?.error?.output?.statusCode;
    if (code === DisconnectReason.loggedOut) {
      console.error('This auth folder is logged out. Delete only this folder and log in again.');
    } else {
      console.error('WhatsApp connection closed before group list was fetched.');
    }
    process.exit(1);
  }
});
