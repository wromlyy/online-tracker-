// whatsapp_notifier.js
// Логинится ВТОРЫМ WhatsApp-аккаунтом. QR присылает в Telegram-бот.
// Уведомления отправляет на ОСНОВНОЙ номер.
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require('@whiskeysockets/baileys');
const express = require('express');
const QRCode = require('qrcode');
const fs = require('fs');
const path = require('path');

// ─── из env ───────────────────────────────────────────────────────────
const TG_BOT_TOKEN     = process.env.TG_BOT_TOKEN;
const TG_CHAT_ID       = process.env.TG_CHAT_ID;
const WA_TARGET_NUMBER = process.env.WA_TARGET_NUMBER;
const WA_CREDS_BASE64  = process.env.WA_CREDS_BASE64 || '';
const NOTIFY_PORT      = parseInt(process.env.WA_NOTIFY_PORT || '8787', 10);
const SESSION_DIR      = process.env.WA_SESSION_DIR || './wa_auth_second';
const LOG_FILE         = 'whatsapp_notifier.log';

if (!TG_BOT_TOKEN || !TG_CHAT_ID) {
  console.error('❌ TG_BOT_TOKEN/TG_CHAT_ID не заданы — QR некуда слать');
  process.exit(1);
}
if (!WA_TARGET_NUMBER) {
  console.error('❌ WA_TARGET_NUMBER не задан — некуда слать уведомления');
  process.exit(1);
}

const TARGET_JID = WA_TARGET_NUMBER + '@s.whatsapp.net';
let sock = null;
let lastQrMessageId = null;
let credsBackupSent = false;

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}`;
  console.log(line);
  try { fs.appendFileSync(LOG_FILE, line + '\n'); } catch (_) {}
}

// ─── Telegram helpers ─────────────────────────────────────────────────
async function tgSendMessage(html) {
  try {
    await fetch(`https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: TG_CHAT_ID, text: html,
        parse_mode: 'HTML', disable_web_page_preview: true,
      }),
    });
  } catch (e) { log(`tgSendMessage: ${e.message}`); }
}

async function tgSendPhoto(buffer, caption) {
  const form = new FormData();
  form.append('chat_id', TG_CHAT_ID);
  form.append('photo', new Blob([buffer], { type: 'image/png' }), 'qr.png');
  form.append('caption', caption);
  const res = await fetch(`https://api.telegram.org/bot${TG_BOT_TOKEN}/sendPhoto`, {
    method: 'POST', body: form,
  });
  const data = await res.json();
  return data.ok ? data.result.message_id : null;
}

async function tgSendDocument(buffer, filename, caption) {
  const form = new FormData();
  form.append('chat_id', TG_CHAT_ID);
  form.append('document', new Blob([buffer], { type: 'application/json' }), filename);
  if (caption) form.append('caption', caption);
  await fetch(`https://api.telegram.org/bot${TG_BOT_TOKEN}/sendDocument`, {
    method: 'POST', body: form,
  });
}

async function tgDeleteMessage(messageId) {
  try {
    await fetch(`https://api.telegram.org/bot${TG_BOT_TOKEN}/deleteMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TG_CHAT_ID, message_id: messageId }),
    });
  } catch (_) {}
}

// ─── QR → Telegram ────────────────────────────────────────────────────
async function sendQrToTelegram(qrString) {
  try {
    const qrBuffer = await QRCode.toBuffer(qrString, { width: 512, margin: 2 });
    const caption =
      '📱 <b>QR для WhatsApp</b>\n\n' +
      'Открой WhatsApp на ВТОРОМ аккаунте:\n' +
      'Связанные устройства → Привязать устройство → сканируй этот QR\n\n' +
      '⏱ QR живёт ~20 секунд, потом придёт новый (старый удалю).';
    const msgId = await tgSendPhoto(qrBuffer, caption);
    if (lastQrMessageId) await tgDeleteMessage(lastQrMessageId);
    lastQrMessageId = msgId;
    log('→ QR отправлен в Telegram');
  } catch (e) {
    log(`sendQrToTelegram: ${e.message}`);
  }
}

// ─── Auth init (с восстановлением из env, если есть) ──────────────────
async function initAuth() {
  if (WA_CREDS_BASE64) {
    try {
      const decoded = Buffer.from(WA_CREDS_BASE64, 'base64').toString('utf-8');
      JSON.parse(decoded); // валидация
      fs.mkdirSync(SESSION_DIR, { recursive: true });
      fs.writeFileSync(path.join(SESSION_DIR, 'creds.json'), decoded);
      log('✅ WA creds восстановлены из WA_CREDS_BASE64');
    } catch (e) {
      log(`⚠️  WA_CREDS_BASE64 битый: ${e.message}`);
    }
  }
  return await useMultiFileAuthState(SESSION_DIR);
}

// ─── Main ─────────────────────────────────────────────────────────────
async function start() {
  const { state, saveCreds } = await initAuth();
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    printQRInTerminal: false,
    syncFullHistory: false,
  });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', async (update) => {
    try {
      const { connection, lastDisconnect, qr } = update;

      if (qr) await sendQrToTelegram(qr);

      if (connection === 'open') {
        log(`✅ WhatsApp подключён, цель: ${WA_TARGET_NUMBER}`);
        tgSendMessage(`✅ <b>WhatsApp подключён</b>\nУведомления будут приходить на ${WA_TARGET_NUMBER}`);
        if (lastQrMessageId) { await tgDeleteMessage(lastQrMessageId); lastQrMessageId = null; }

        // Один раз шлём бэкап creds — на случай если файловая система не сохранится
        if (!credsBackupSent) {
          credsBackupSent = true;
          try {
            const credsPath = path.join(SESSION_DIR, 'creds.json');
            const buf = fs.readFileSync(credsPath);
            const b64 = buf.toString('base64');
            await tgSendDocument(buf, 'wa_creds.json',
              '💾 Бэкап WhatsApp-сессии.\n\n' +
              'Если после рестарта бот снова просит QR — сохрани этот файл как ' +
              'env-переменную WA_CREDS_BASE64 (значение base64) и перезапусти.');
            // Второе сообщение с готовой base64-строкой — удобно копировать
            if (b64.length < 3800) {
              await tgSendMessage(
                '📋 <b>Готовая строка для WA_CREDS_BASE64:</b>\n\n' +
                `<code>${b64}</code>`
              );
            } else {
              await tgSendMessage(
                'ℹ️ Base64 слишком длинный для одного сообщения — ' +
                'используй скачанный файл wa_creds.json: ' +
                'преобразуй сам в base64 и вставь в WA_CREDS_BASE64.'
              );
            }
          } catch (e) {
            log(`creds backup: ${e.message}`);
          }
        }
      }

      if (connection === 'close') {
        const code = lastDisconnect?.error?.output?.statusCode;
        const loggedOut = code === DisconnectReason.loggedOut;
        log(`❌ WA отключён (code=${code})${loggedOut ? ' — разлогинен' : ', реконнект…'}`);
        if (loggedOut) {
          // сессия мертва — стираем и ждём новый QR
          try { fs.rmSync(SESSION_DIR, { recursive: true, force: true }); } catch (_) {}
          tgSendMessage('⚠️ WhatsApp разлогинился. Сейчас пришлю новый QR.');
        }
        setTimeout(start, 5000);
      }
    } catch (e) {
      log(`connection.update error: ${e.message}`);
    }
  });
}

// ─── HTTP-приёмник от python notifier ─────────────────────────────────
const app = express();
app.use(express.json());
app.post('/notify', async (req, res) => {
  const { text } = req.body || {};
  if (!text || !sock) return res.status(400).json({ ok: false });
  try {
    await sock.sendMessage(TARGET_JID, { text });
    log(`→ отправлено на ${WA_TARGET_NUMBER}: ${text.replace(/<[^>]+>/g, '')}`);
    res.json({ ok: true });
  } catch (e) {
    log(`⚠️ sendMessage: ${e.message}`);
    res.status(500).json({ ok: false, error: e.message });
  }
});
app.listen(NOTIFY_PORT, () => log(`📨 WA-приёмник на :${NOTIFY_PORT}`));

start();
