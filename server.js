const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const path = require('path');
const { v4: uuidv4 } = require('uuid');

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

app.use(express.static(path.join(__dirname, 'public')));
app.use('/uploads', express.static(path.join(__dirname, 'uploads')));

// Хранилище (в продакшене заменить на БД)
const users = new Map();        // nickname -> { password, online, ws }
const messages = new Map();     // chatId -> [messages]
const contacts = new Map();     // nickname -> [contacts]
const onlineUsers = new Map();  // ws -> nickname

function getChatId(user1, user2) {
    return [user1, user2].sort().join('::');
}

function broadcast(nickname, data) {
    const user = users.get(nickname);
    if (user && user.ws && user.ws.readyState === WebSocket.OPEN) {
        user.ws.send(JSON.stringify(data));
    }
}

wss.on('connection', (ws) => {
    console.log('Новое подключение');

    ws.on('message', (rawData) => {
        let data;
        try {
            data = JSON.parse(rawData);
        } catch (e) {
            return;
        }

        switch (data.type) {
            case 'register': {
                const { nickname } = data;
                if (!nickname || nickname.trim().length < 2) {
                    ws.send(JSON.stringify({ type: 'error', message: 'Никнейм минимум 2 символа' }));
                    return;
                }
                const nick = nickname.trim().toLowerCase();
                if (users.has(nick)) {
                    // Логин
                    const user = users.get(nick);
                    user.ws = ws;
                    user.online = true;
                } else {
                    // Регистрация
                    users.set(nick, { online: true, ws });
                    contacts.set(nick, []);
                }
                onlineUsers.set(ws, nick);

                // Отправить подтверждение
                ws.send(JSON.stringify({
                    type: 'auth_success',
                    nickname: nick,
                    contacts: contacts.get(nick) || []
                }));

                // Уведомить контакты что онлайн
                const userContacts = contacts.get(nick) || [];
                userContacts.forEach(contact => {
                    broadcast(contact, {
                        type: 'user_status',
                        nickname: nick,
                        online: true
                    });
                });
                break;
            }

            case 'search_user': {
                const { query } = data;
                const nick = query.trim().toLowerCase();
                const myNick = onlineUsers.get(ws);
                if (users.has(nick) && nick !== myNick) {
                    const targetUser = users.get(nick);
                    ws.send(JSON.stringify({
                        type: 'search_result',
                        found: true,
                        nickname: nick,
                        online: targetUser.online
                    }));
                } else if (nick === myNick) {
                    ws.send(JSON.stringify({
                        type: 'search_result',
                        found: false,
                        message: 'Это вы сами!'
                    }));
                } else {
                    ws.send(JSON.stringify({
                        type: 'search_result',
                        found: false,
                        message: 'Пользователь не найден'
                    }));
                }
                break;
            }

            case 'add_contact': {
                const myNick = onlineUsers.get(ws);
                const contactNick = data.nickname;
                if (!myNick || !contactNick) return;

                const myContacts = contacts.get(myNick) || [];
                if (!myContacts.includes(contactNick)) {
                    myContacts.push(contactNick);
                    contacts.set(myNick, myContacts);
                }

                const theirContacts = contacts.get(contactNick) || [];
                if (!theirContacts.includes(myNick)) {
                    theirContacts.push(myNick);
                    contacts.set(contactNick, theirContacts);
                }

                ws.send(JSON.stringify({
                    type: 'contact_added',
                    nickname: contactNick,
                    online: users.get(contactNick)?.online || false
                }));

                broadcast(contactNick, {
                    type: 'contact_added',
                    nickname: myNick,
                    online: true
                });
                break;
            }

            case 'send_message': {
                const myNick = onlineUsers.get(ws);
                const { to, content, messageType, fileName, fileData } = data;
                if (!myNick || !to) return;

                const chatId = getChatId(myNick, to);
                const msg = {
                    id: uuidv4(),
                    from: myNick,
                    to: to,
                    content: content || '',
                    messageType: messageType || 'text', // text, image, video, file
                    fileName: fileName || '',
                    fileData: fileData || '',
                    timestamp: Date.now(),
                    read: false
                };

                if (!messages.has(chatId)) {
                    messages.set(chatId, []);
                }
                messages.get(chatId).push(msg);

                // Отправить обоим
                const msgForSend = { type: 'new_message', message: msg };
                ws.send(JSON.stringify(msgForSend));
                broadcast(to, msgForSend);
                break;
            }

            case 'load_messages': {
                const myNick = onlineUsers.get(ws);
                const { with: withUser } = data;
                if (!myNick || !withUser) return;

                const chatId = getChatId(myNick, withUser);
                const chatMessages = messages.get(chatId) || [];

                // Отметить как прочитанные
                chatMessages.forEach(msg => {
                    if (msg.to === myNick) msg.read = true;
                });

                ws.send(JSON.stringify({
                    type: 'messages_loaded',
                    with: withUser,
                    messages: chatMessages
                }));
                break;
            }

            case 'typing': {
                const myNick = onlineUsers.get(ws);
                const { to } = data;
                broadcast(to, {
                    type: 'typing',
                    from: myNick
                });
                break;
            }

            case 'get_contacts': {
                const myNick = onlineUsers.get(ws);
                if (!myNick) return;
                const userContacts = contacts.get(myNick) || [];
                const contactList = userContacts.map(nick => ({
                    nickname: nick,
                    online: users.get(nick)?.online || false,
                    lastMessage: getLastMessage(myNick, nick),
                    unread: getUnreadCount(myNick, nick)
                }));
                ws.send(JSON.stringify({
                    type: 'contacts_list',
                    contacts: contactList
                }));
                break;
            }
        }
    });

    ws.on('close', () => {
        const nick = onlineUsers.get(ws);
        if (nick) {
            const user = users.get(nick);
            if (user) {
                user.online = false;
                user.ws = null;
            }
            onlineUsers.delete(ws);

            // Уведомить контакты
            const userContacts = contacts.get(nick) || [];
            userContacts.forEach(contact => {
                broadcast(contact, {
                    type: 'user_status',
                    nickname: nick,
                    online: false
                });
            });
        }
    });
});

function getLastMessage(user1, user2) {
    const chatId = getChatId(user1, user2);
    const msgs = messages.get(chatId) || [];
    if (msgs.length === 0) return null;
    const last = msgs[msgs.length - 1];
    return {
        content: last.messageType === 'text' ? last.content : `📎 ${last.fileName || last.messageType}`,
        timestamp: last.timestamp,
        from: last.from
    };
}

function getUnreadCount(myNick, otherNick) {
    const chatId = getChatId(myNick, otherNick);
    const msgs = messages.get(chatId) || [];
    return msgs.filter(m => m.to === myNick && !m.read).length;
}

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
    console.log(`🚀 Сервер запущен на http://localhost:${PORT}`);
});