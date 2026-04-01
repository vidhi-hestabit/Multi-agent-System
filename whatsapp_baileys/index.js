require('dotenv').config({ path: require('path').resolve(__dirname, '../.env.local') });
const express = require('express');
const { 
    default: makeWASocket, 
    fetchLatestBaileysVersion, 
    DisconnectReason,
    AuthenticationState,
    SignalDataTypeMap,
    initAuthCreds,
    BufferJSON
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const axios = require('axios');
const { MongoClient } = require('mongodb');

const app = express();
app.use(express.json());

const PORT = 8080;
const WEBHOOK_URL = 'http://127.0.0.1:8031/webhook';
const instances = {};

// Logger
const logger = pino({ level: 'silent' });

// ----------------------------------------------------
// MongoDB Auth State Implementation
// ----------------------------------------------------

async function useMongoDBAuthState(instanceName) {
    const client = new MongoClient(process.env.MONGODB_URL);
    await client.connect();
    const db = client.db(process.env.MONGODB_DB || 'multi-agent-system');
    const collection = db.collection('whatsapp_sessions');

    const writeData = async (data, id) => {
        return collection.updateOne(
            { instanceName, id },
            { $set: { data: JSON.stringify(data, BufferJSON.replacer) } },
            { upsert: true }
        );
    };

    const readData = async (id) => {
        try {
            const res = await collection.findOne({ instanceName, id });
            return res ? JSON.parse(res.data, BufferJSON.reviver) : null;
        } catch (error) {
            return null;
        }
    };

    const removeData = async (id) => {
        try {
            await collection.deleteOne({ instanceName, id });
        } catch (error) {
            logger.error(`Error removing data ${id}: ${error}`);
        }
    };

    const creds = await readData('creds') || initAuthCreds();

    return {
        state: {
            creds,
            keys: {
                get: async (type, ids) => {
                    const data = {};
                    await Promise.all(
                        ids.map(async (id) => {
                            let value = await readData(`${type}-${id}`);
                            if (type === 'app-state-sync-key' && value) {
                                value = BufferJSON.fromJSON(value);
                            }
                            data[id] = value;
                        })
                    );
                    return data;
                },
                set: async (data) => {
                    const tasks = [];
                    for (const category in data) {
                        for (const id in data[category]) {
                            const value = data[category][id];
                            const key = `${category}-${id}`;
                            tasks.push(value ? writeData(value, key) : removeData(key));
                        }
                    }
                    await Promise.all(tasks);
                }
            }
        },
        saveCreds: () => writeData(creds, 'creds'),
        close: () => client.close()
    };
}

// ----------------------------------------------------
// Instance Management
// ----------------------------------------------------

async function createInstance(instanceName) {
    if (instances[instanceName]) return;

    console.log(`[Baileys] Creating instance: ${instanceName} (MongoDB Storage)`);
    
    const { state, saveCreds, close } = await useMongoDBAuthState(instanceName);
    const { version } = await fetchLatestBaileysVersion();
    
    const sock = makeWASocket({
        version,
        auth: state,
        logger,
        printQRInTerminal: true,
        browser: ["Nexus MAS", "Chrome", "10.0.0"]
    });

    instances[instanceName] = {
        name: instanceName,
        sock,
        qr: null,
        connectionState: 'connecting',
        mongoClose: close
    };

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
                setTimeout(() => {
                    if (instances[instanceName]) {
                        if (instances[instanceName].mongoClose) instances[instanceName].mongoClose();
                        delete instances[instanceName];
                    }
                    createInstance(instanceName);
                }, 5000);
            } else {
                // Logged out: clean MongoDB
                const client = new MongoClient(process.env.MONGODB_URL);
                client.connect().then(async () => {
                    const db = client.db(process.env.MONGODB_DB || 'multi-agent-system');
                    await db.collection('whatsapp_sessions').deleteMany({ instanceName });
                    client.close();
                });
                if (instances[instanceName].mongoClose) instances[instanceName].mongoClose();
                delete instances[instanceName];
            }
        } 
        else if (connection === 'open') {
            console.log(`[Baileys] ${instanceName} connected successfully!`);
            instances[instanceName].connectionState = 'open';
            instances[instanceName].qr = null;
            
            axios.post(WEBHOOK_URL, {
                event: 'connection.update',
                instance: instanceName,
                data: { state: 'open', statusReason: 200 }
            }).catch(e => {});
        }
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('messages.upsert', async (m) => {
        const msg = m.messages[0];
        if (!msg.message || msg.key.fromMe) return;

        console.log(`[Baileys] ${instanceName} received message`);
        
        axios.post(WEBHOOK_URL, {
            event: 'messages.upsert',
            instance: instanceName,
            data: { message: msg }
        }).catch(e => {});
    });
}

// Ensure instances are loaded on startup if they were already connected?
// For now, they load on demand via /instance/create or first message.

// ----------------------------------------------------
// API Endpoints
// ----------------------------------------------------

app.get('/instance/fetchInstances', (req, res) => {
    const list = Object.keys(instances).map(name => ({
        instance: { instanceName: name }
    }));
    res.json(list);
});

app.post('/instance/create', async (req, res) => {
    const { instanceName } = req.body;
    if (instanceName) {
        await createInstance(instanceName);
    }
    res.json({ status: 'SUCCESS' });
});

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

app.get('/instance/connectionState/:instanceName', (req, res) => {
    const inst = instances[req.params.instanceName];
    if (!inst) return res.json({ instance: { state: 'close' } });

    res.json({ instance: { state: inst.connectionState } });
});

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

app.listen(PORT, '0.0.0.0', async () => {
    console.log(`[Baileys Server] MongoDB-backed proxy running on port ${PORT}`);
    
    // Auto-load existing instances from MongoDB
    try {
        const client = new MongoClient(process.env.MONGODB_URL);
        await client.connect();
        const db = client.db(process.env.MONGODB_DB || 'multi-agent-system');
        const collection = db.collection('whatsapp_sessions');
        
        const uniqueInstances = await collection.distinct('instanceName');
        console.log(`[Baileys] Found ${uniqueInstances.length} sessions in MongoDB. Restoring...`);
        
        for (const name of uniqueInstances) {
            createInstance(name).catch(err => console.error(`Failed to restore ${name}:`, err));
        }
        await client.close();
    } catch (err) {
        console.error('Failed to auto-load instances:', err);
    }
});

