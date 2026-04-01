const express = require('express');
const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason } = require('@whiskeysockets/baileys');
const pino = require('pino');
const axios = require('axios');
const fs = require('fs');

const app = express();
app.use(express.json());

const PORT = 8080;
const WEBHOOK_URL = 'http://127.0.0.1:8031/webhook';
const instances = {};

// Logger
const logger = pino({ level: 'silent' });

async function createInstance(instanceName) {
    if (instances[instanceName]) return;

    console.log(`[Baileys] Creating instance: ${instanceName}`);
    
    const { state, saveCreds } = await useMultiFileAuthState(`./sessions/${instanceName}`);
    const { version } = await fetchLatestBaileysVersion();
    
    // Create socket
    const sock = makeWASocket({
        version,
        auth: state,
        logger,
        printQRInTerminal: true, // Also prints to terminal for debugging
        browser: ["Nexus MAS", "Chrome", "10.0.0"]
    });

    instances[instanceName] = {
        name: instanceName,
        sock,
        qr: null,
        connectionState: 'connecting'
    };

    // Connection Events
    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        
        if (qr) {
            console.log(`[Baileys] ${instanceName} generated QR`);
            const qrcode = require('qrcode');
            qrcode.toDataURL(qr, (err, url) => {
                if (!err) instances[instanceName].qr = url;
            });
        }
        
        if (connection === 'close') {
            const shouldReconnect = lastDisconnect.error?.output?.statusCode !== DisconnectReason.loggedOut;
            instances[instanceName].connectionState = 'close';
            
            console.log(`[Baileys] ${instanceName} closed. Reconnecting: ${shouldReconnect}`);
            
            if (shouldReconnect) {
                // Remove socket and recreate logic
                setTimeout(() => {
                    delete instances[instanceName];
                    createInstance(instanceName);
                }, 5000);
            } else {
                // Logged out
                fs.rmSync(`./sessions/${instanceName}`, { recursive: true, force: true });
                delete instances[instanceName];
            }
        } 
        else if (connection === 'open') {
            console.log(`[Baileys] ${instanceName} connected successfully!`);
            instances[instanceName].connectionState = 'open';
            instances[instanceName].qr = null;
            
            // Fire webhook
            axios.post(WEBHOOK_URL, {
                event: 'connection.update',
                instance: instanceName,
                data: { state: 'open', statusReason: 200 }
            }).catch(e => console.log('Webhook error on open'));
        }
    });

    sock.ev.on('creds.update', saveCreds);

    // Messages Webhook
    sock.ev.on('messages.upsert', async (m) => {
        const msg = m.messages[0];
        if (!msg.message || msg.key.fromMe) return;

        console.log(`[Baileys] ${instanceName} received message from ${msg.key.remoteJid}`);
        
        // Fire webhook
        axios.post(WEBHOOK_URL, {
            event: 'messages.upsert',
            instance: instanceName,
            data: { message: msg }
        }).catch(e => console.log('Webhook error on message'));
    });
}

// ----------------------------------------------------
// Mock Evolution API Endpoints
// ----------------------------------------------------

// /instance/fetchInstances
app.get('/instance/fetchInstances', (req, res) => {
    const list = Object.keys(instances).map(name => ({
        instance: { instanceName: name }
    }));
    res.json(list);
});

// /instance/create
app.post('/instance/create', async (req, res) => {
    const { instanceName } = req.body;
    if (instanceName) {
        await createInstance(instanceName);
    }
    res.json({ status: 'SUCCESS' });
});

// /instance/connect/:instanceMap
app.get('/instance/connect/:instanceName', (req, res) => {
    const inst = instances[req.params.instanceName];
    if (!inst) return res.json({ count: 0 });

    if (inst.connectionState === 'open') {
        return res.json({ instance: { state: 'open' } });
    }
    
    if (inst.qr) {
        return res.json({ base64: inst.qr });
    }
    
    res.json({ count: 0 });
});

// /instance/connectionState/:instanceName
app.get('/instance/connectionState/:instanceName', (req, res) => {
    const inst = instances[req.params.instanceName];
    if (!inst) return res.json({ instance: { state: 'close' } });

    res.json({ instance: { state: inst.connectionState } });
});

// /message/sendText/:instanceName
app.post('/message/sendText/:instanceName', async (req, res) => {
    const inst = instances[req.params.instanceName];
    if (!inst || inst.connectionState !== 'open') {
        return res.status(400).json({ error: 'Instance not connected' });
    }

    const { number, text } = req.body;
    const jid = number.includes('@') ? number : `${number}@s.whatsapp.net`;

    try {
        await inst.sock.sendMessage(jid, { text });
        res.json({ status: 'SUCCESS' });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

app.listen(PORT, '0.0.0.0', () => {
    console.log(`[Baileys Server] Evolution API mocking proxy running on port ${PORT}`);
});
