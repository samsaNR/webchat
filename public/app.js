class WebChat {
    constructor() {
        this.ws = null;
        this.nickname = '';
        this.currentChat = null;
        this.contacts = [];
        this.messagesCache = {};
        this.typingTimeout = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.pendingFiles = [];

        this.init();
    }

    init() {
        // Проверяем сохранённый никнейм
        const saved = localStorage.getItem('webchat_nickname');
        if (saved) {
            this.nickname = saved;
            this.connect();
        }

        this.bindEvents();
        this.loadLocalData();
    }

    // ===== WebSocket =====

    connect() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${location.host}`);

        this.ws.onopen = () => {
            console.log('✅ Подключено');
            this.reconnectAttempts = 0;
            if (this.nickname) {
                this.send({ type: 'register', nickname: this.nickname });
            }
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        };

        this.ws.onclose = () => {
            console.log('❌ Отключено');
            this.reconnect();
        };

        this.ws.onerror = (err) => {
            console.error('WS Error:', err);
        };
    }

    reconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
            console.log(`Переподключение через ${delay / 1000}с...`);
            setTimeout(() => this.connect(), delay);
        }
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }

    // ===== Обработка сообщений =====

    handleMessage(data) {
        switch (data.type) {
            case 'auth_success':
                this.onAuthSuccess(data);
                break;
            case 'error':
                this.showToast(data.message, 'error');
                break;
            case 'search_result':
                this.onSearchResult(data);
                break;
            case 'contact_added':
                this.onContactAdded(data);
                break;
            case 'contacts_list':
                this.onContactsList(data);
                break;
            case 'new_message':
                this.onNewMessage(data.message);
                break;
            case 'messages_loaded':
                this.onMessagesLoaded(data);
                break;
            case 'user_status':
                this.onUserStatus(data);
                break;
            case 'typing':
                this.onTyping(data);
                break;
        }
    }

    onAuthSuccess(data) {
        this.nickname = data.nickname;
        localStorage.setItem('webchat_nickname', this.nickname);

        // Показать основной экран
        document.getElementById('loginScreen').classList.remove('active');
        document.getElementById('mainScreen').classList.add('active');
        document.getElementById('myNickname').textContent = '@' + this.nickname;
        document.getElementById('myAvatar').textContent = this.nickname[0].toUpperCase();

        // Запросить контакты
        this.send({ type: 'get_contacts' });

        this.showToast(`Привет, @${this.nickname}!`, 'success');
    }

    onSearchResult(data) {
        const results = document.getElementById('searchResults');
        if (data.found) {
            const isContact = this.contacts.some(c => c.nickname === data.nickname);
            results.innerHTML = `
                <div class="search-result-item">
                    <div class="search-result-user">
                        <div class="avatar">${data.nickname[0].toUpperCase()}</div>
                        <div>
                            <div style="font-weight:600">@${data.nickname}</div>
                            <div style="font-size:12px;color:${data.online ? 'var(--success)' : 'var(--text-muted)'}">
                                ${data.online ? 'онлайн' : 'оффлайн'}
                            </div>
                        </div>
                    </div>
                    ${isContact ?
                        `<button class="btn-add" onclick="chat.openChat('${data.nickname}')">Открыть</button>` :
                        `<button class="btn-add" onclick="chat.addContact('${data.nickname}')">Добавить</button>`
                    }
                </div>
            `;
        } else {
            results.innerHTML = `<div class="search-message">${data.message}</div>`;
        }
    }

    onContactAdded(data) {
        const exists = this.contacts.some(c => c.nickname === data.nickname);
        if (!exists) {
            this.contacts.push({
                nickname: data.nickname,
                online: data.online,
                lastMessage: null,
                unread: 0
            });
            this.renderContacts();
            this.saveLocalData();
        }
    }

    onContactsList(data) {
        this.contacts = data.contacts;
        this.renderContacts();
        this.saveLocalData();
    }

    onNewMessage(msg) {
        const chatPartner = msg.from === this.nickname ? msg.to : msg.from;

        // Кэшировать
        if (!this.messagesCache[chatPartner]) {
            this.messagesCache[chatPartner] = [];
        }
        // Проверить дубликат
        if (!this.messagesCache[chatPartner].some(m => m.id === msg.id)) {
            this.messagesCache[chatPartner].push(msg);
        }

        // Сохранить в localStorage
        this.saveLocalData();

        // Если текущий чат — показать
        if (this.currentChat === chatPartner) {
            this.appendMessage(msg);
            this.scrollToBottom();
        }

        // Обновить контакт
        this.updateContactLastMessage(chatPartner, msg);

        // Уведомление если не в текущем чате
        if (msg.from !== this.nickname && this.currentChat !== msg.from) {
            this.playNotification();
            this.showNotification(msg);
        }

        // Сохранить медиа в localStorage для оффлайн доступа
        if (msg.messageType === 'image' || msg.messageType === 'video') {
            this.saveMediaLocally(msg);
        }
    }

    onMessagesLoaded(data) {
        this.messagesCache[data.with] = data.messages;
        this.renderMessages(data.messages);
        this.saveLocalData();
    }

    onUserStatus(data) {
        const contact = this.contacts.find(c => c.nickname === data.nickname);
        if (contact) {
            contact.online = data.online;
            this.renderContacts();
        }

        if (this.currentChat === data.nickname) {
            const statusEl = document.getElementById('chatStatus');
            statusEl.textContent = data.online ? 'онлайн' : 'оффлайн';
            statusEl.className = 'chat-status' + (data.online ? ' online' : '');
        }
    }

    onTyping(data) {
        if (this.currentChat === data.from) {
            const indicator = document.getElementById('typingIndicator');
            indicator.classList.remove('hidden');
            clearTimeout(this._typingHideTimeout);
            this._typingHideTimeout = setTimeout(() => {
                indicator.classList.add('hidden');
            }, 2000);
        }
    }

    // ===== Действия =====

    login() {
        const input = document.getElementById('nicknameInput');
        const nickname = input.value.trim();
        if (nickname.length < 2) {
            this.showToast('Минимум 2 символа', 'error');
            return;
        }
        this.nickname = nickname.toLowerCase();
        this.connect();
    }

    addContact(nickname) {
        this.send({ type: 'add_contact', nickname });
        document.getElementById('searchPanel').classList.add('hidden');
        document.getElementById('searchInput').value = '';
        document.getElementById('searchResults').innerHTML = '';
    }

    searchUser() {
        const query = document.getElementById('searchInput').value.trim();
        if (query.length < 2) {
            this.showToast('Минимум 2 символа', 'error');
            return;
        }
        this.send({ type: 'search_user', query: query.toLowerCase() });
    }

    openChat(nickname) {
        this.currentChat = nickname;
        const contact = this.contacts.find(c => c.nickname === nickname);

        // UI
        document.getElementById('chatUsername').textContent = '@' + nickname;
        document.getElementById('chatAvatar').textContent = nickname[0].toUpperCase();
        const statusEl = document.getElementById('chatStatus');
        const isOnline = contact?.online || false;
        statusEl.textContent = isOnline ? 'онлайн' : 'оффлайн';
        statusEl.className = 'chat-status' + (isOnline ? ' online' : '');

        // Показать чат
        document.getElementById('chatScreen').classList.add('active');
        document.getElementById('chatList').classList.add('hidden-left');

        // Скрыть поиск
        document.getElementById('searchPanel').classList.add('hidden');

        // Загрузить сообщения
        if (this.messagesCache[nickname]?.length) {
            this.renderMessages(this.messagesCache[nickname]);
        } else {
            document.getElementById('messagesWrapper').innerHTML = '';
        }

        // Запросить с сервера
        this.send({ type: 'load_messages', with: nickname });

        // Сбросить непрочитанные
        if (contact) {
            contact.unread = 0;
            this.renderContacts();
        }

        // Фокус на ввод
        setTimeout(() => {
            document.getElementById('messageInput').focus();
        }, 300);
    }

    closeChat() {
        this.currentChat = null;
        document.getElementById('chatScreen').classList.remove('active');
        document.getElementById('chatList').classList.remove('hidden-left');
        document.getElementById('typingIndicator').classList.add('hidden');
        this.clearFilePreview();
    }

    sendMessage() {
        const input = document.getElementById('messageInput');
        const text = input.value.trim();

        if (!this.currentChat) return;

        // Отправить файлы если есть
        if (this.pendingFiles.length > 0) {
            this.pendingFiles.forEach(file => {
                this.send({
                    type: 'send_message',
                    to: this.currentChat,
                    content: '',
                    messageType: file.type,
                    fileName: file.name,
                    fileData: file.data
                });
            });
            this.clearFilePreview();
        }

        // Отправить текст
        if (text) {
            this.send({
                type: 'send_message',
                to: this.currentChat,
                content: text,
                messageType: 'text'
            });
            input.value = '';
            input.style.height = 'auto';
        }

        if (!text && this.pendingFiles.length === 0) return;
    }

    sendTyping() {
        if (!this.currentChat) return;
        if (this.typingTimeout) return;
        this.send({ type: 'typing', to: this.currentChat });
        this.typingTimeout = setTimeout(() => {
            this.typingTimeout = null;
        }, 1000);
    }

    // ===== Файлы =====

    handleFileSelect(e) {
        const files = Array.from(e.target.files);
        if (!files.length) return;

        this.pendingFiles = [];
        const preview = document.getElementById('filePreview');
        const previewImg = document.getElementById('filePreviewImg');
        const previewVideo = document.getElementById('filePreviewVideo');
        const previewFile = document.getElementById('filePreviewFile');

        let processed = 0;

        files.forEach(file => {
            // Лимит 10MB
            if (file.size > 10 * 1024 * 1024) {
                this.showToast(`${file.name} слишком большой (макс 10МБ)`, 'error');
                return;
            }

            const reader = new FileReader();
            reader.onload = (ev) => {
                const base64 = ev.target.result;
                let fileType = 'file';
                if (file.type.startsWith('image/')) fileType = 'image';
                else if (file.type.startsWith('video/')) fileType = 'video';

                this.pendingFiles.push({
                    type: fileType,
                    name: file.name,
                    data: base64
                });

                processed++;
                if (processed === files.length || this.pendingFiles.length > 0) {
                    // Показать превью первого файла
                    const first = this.pendingFiles[0];
                    previewImg.classList.add('hidden');
                    previewVideo.classList.add('hidden');
                    previewFile.classList.add('hidden');

                    if (first.type === 'image') {
                        previewImg.src = first.data;
                        previewImg.classList.remove('hidden');
                    } else if (first.type === 'video') {
                        previewVideo.src = first.data;
                        previewVideo.classList.remove('hidden');
                    } else {
                        document.getElementById('filePreviewName').textContent = first.name;
                        previewFile.classList.remove('hidden');
                    }

                    preview.classList.remove('hidden');
                }
            };
            reader.readAsDataURL(file);
        });

        e.target.value = '';
    }

    clearFilePreview() {
        this.pendingFiles = [];
        document.getElementById('filePreview').classList.add('hidden');
        document.getElementById('filePreviewImg').classList.add('hidden');
        document.getElementById('filePreviewVideo').classList.add('hidden');
        document.getElementById('filePreviewFile').classList.add('hidden');
    }

    // ===== Рендеринг =====

    renderContacts() {
        const container = document.getElementById('contactsList');

        if (this.contacts.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">👋</div>
                    <p>Пока нет чатов</p>
                    <p class="sub">Нажмите 🔍 чтобы найти собеседника</p>
                </div>
            `;
            return;
        }

        // Сортировка: последнее сообщение сверху
        const sorted = [...this.contacts].sort((a, b) => {
            const timeA = a.lastMessage?.timestamp || 0;
            const timeB = b.lastMessage?.timestamp || 0;
            return timeB - timeA;
        });

        container.innerHTML = sorted.map(contact => {
            const initial = contact.nickname[0].toUpperCase();
            const lastMsg = contact.lastMessage;
            const timeStr = lastMsg ? this.formatTime(lastMsg.timestamp) : '';
            const msgPreview = lastMsg ? this.escapeHtml(lastMsg.content).substring(0, 40) : 'Нет сообщений';
            const unread = contact.unread || 0;

            return `
                <div class="contact-item" onclick="chat.openChat('${contact.nickname}')">
                    <div class="contact-avatar">
                        ${initial}
                        <div class="online-indicator ${contact.online ? '' : 'offline'}"></div>
                    </div>
                    <div class="contact-info">
                        <span class="contact-name">@${contact.nickname}</span>
                        <span class="contact-last-msg">${msgPreview}</span>
                    </div>
                    <div class="contact-meta">
                        <span class="contact-time">${timeStr}</span>
                        ${unread > 0 ? `<div class="unread-badge">${unread}</div>` : ''}
                    </div>
                </div>
            `;
        }).join('');
    }

    renderMessages(messages) {
        const wrapper = document.getElementById('messagesWrapper');
        wrapper.innerHTML = '';

        let lastDate = '';

        messages.forEach(msg => {
            const msgDate = new Date(msg.timestamp).toLocaleDateString('ru-RU');
            if (msgDate !== lastDate) {
                lastDate = msgDate;
                const divider = document.createElement('div');
                divider.className = 'date-divider';
                divider.innerHTML = `<span>${this.formatDate(msg.timestamp)}</span>`;
                wrapper.appendChild(divider);
            }

            this.appendMessageElement(wrapper, msg);
        });

        this.scrollToBottom();
    }

    appendMessage(msg) {
        const wrapper = document.getElementById('messagesWrapper');

        // Проверяем дату
        const lastDateDivider = wrapper.querySelector('.date-divider:last-of-type');
        const msgDate = new Date(msg.timestamp).toLocaleDateString('ru-RU');
        const lastDate = lastDateDivider?.textContent || '';
        if (msgDate !== lastDate) {
            const divider = document.createElement('div');
            divider.className = 'date-divider';
            divider.innerHTML = `<span>${this.formatDate(msg.timestamp)}</span>`;
            wrapper.appendChild(divider);
        }

        // Проверка дубликата в DOM
        if (wrapper.querySelector(`[data-msg-id="${msg.id}"]`)) return;

        this.appendMessageElement(wrapper, msg);
    }

    appendMessageElement(container, msg) {
        const div = document.createElement('div');
        div.className = `message ${msg.from === this.nickname ? 'own' : 'other'}`;
        div.dataset.msgId = msg.id;

        let content = '';

        if (msg.messageType === 'image') {
            content = `
                <div class="message-media" onclick="chat.openMedia('${msg.id}', 'image')">
                    <img src="${msg.fileData}" alt="${msg.fileName}" loading="lazy">
                </div>
            `;
        } else if (msg.messageType === 'video') {
            content = `
                <div class="message-media">
                    <video src="${msg.fileData}" preload="metadata" onclick="chat.openMedia('${msg.id}', 'video')"></video>
                </div>
            `;
        } else if (msg.messageType === 'file') {
            content = `
                <div class="message-file" onclick="chat.downloadFile('${msg.fileData}', '${msg.fileName}')">
                    <span class="file-icon">📄</span>
                    <span class="file-name">${this.escapeHtml(msg.fileName)}</span>
                    <span class="file-download">⬇️</span>
                </div>
            `;
        }

        if (msg.content) {
            content += `<div class="message-text">${this.linkify(this.escapeHtml(msg.content))}</div>`;
        }

        content += `<div class="message-time">${this.formatTime(msg.timestamp)}</div>`;

        div.innerHTML = content;
        container.appendChild(div);
    }

    updateContactLastMessage(nickname, msg) {
        let contact = this.contacts.find(c => c.nickname === nickname);
        if (!contact) {
            // Автоматически добавить контакт
            contact = {
                nickname: nickname,
                online: true,
                lastMessage: null,
                unread: 0
            };
            this.contacts.push(contact);
        }

        contact.lastMessage = {
            content: msg.messageType === 'text' ? msg.content : `📎 ${msg.fileName || msg.messageType}`,
            timestamp: msg.timestamp,
            from: msg.from
        };

        if (msg.from !== this.nickname && this.currentChat !== nickname) {
            contact.unread = (contact.unread || 0) + 1;
        }

        this.renderContacts();
    }

    // ===== Медиа =====

    openMedia(msgId, type) {
        const modal = document.getElementById('mediaModal');
        const modalImg = document.getElementById('modalImage');
        const modalVideo = document.getElementById('modalVideo');

        modalImg.classList.add('hidden');
        modalVideo.classList.add('hidden');

        // Найти сообщение
        let msg = null;
        for (const key of Object.keys(this.messagesCache)) {
            msg = this.messagesCache[key]?.find(m => m.id === msgId);
            if (msg) break;
        }

        if (!msg) return;

        if (type === 'image') {
            modalImg.src = msg.fileData;
            modalImg.classList.remove('hidden');
        } else if (type === 'video') {
            modalVideo.src = msg.fileData;
            modalVideo.classList.remove('hidden');
        }

        // Кнопка скачивания
        document.getElementById('mediaModalDownload').onclick = () => {
            this.downloadFile(msg.fileData, msg.fileName);
        };

        modal.classList.remove('hidden');
    }

    closeMedia() {
        const modal = document.getElementById('mediaModal');
        modal.classList.add('hidden');
        document.getElementById('modalVideo').pause();
    }

    downloadFile(dataUrl, fileName) {
        const link = document.createElement('a');
        link.href = dataUrl;
        link.download = fileName || 'download';
        link.click();
    }

    downloadChat() {
        if (!this.currentChat) return;
        const messages = this.messagesCache[this.currentChat] || [];
        if (messages.length === 0) {
            this.showToast('Нет сообщений для скачивания', 'error');
            return;
        }

        let text = `Чат с @${this.currentChat}\n`;
        text += `Экспорт: ${new Date().toLocaleString('ru-RU')}\n`;
        text += '═'.repeat(40) + '\n\n';

        messages.forEach(msg => {
            const time = new Date(msg.timestamp).toLocaleString('ru-RU');
            const from = msg.from === this.nickname ? 'Вы' : `@${msg.from}`;
            let content = msg.content;
            if (msg.messageType !== 'text') {
                content = `[${msg.messageType}: ${msg.fileName}]`;
            }
            text += `[${time}] ${from}: ${content}\n`;
        });

        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `chat_${this.currentChat}_${Date.now()}.txt`;
        link.click();
        URL.revokeObjectURL(url);

        this.showToast('Чат скачан!', 'success');
    }

    // ===== Локальное хранилище =====

    saveLocalData() {
        try {
            const data = {
                contacts: this.contacts,
                messages: this.messagesCache
            };
            localStorage.setItem('webchat_data', JSON.stringify(data));
        } catch (e) {
            // localStorage может быть переполнен
            console.warn('Не удалось сохранить данные:', e);
            this.cleanupOldData();
        }
    }

    loadLocalData() {
        try {
            const raw = localStorage.getItem('webchat_data');
            if (raw) {
                const data = JSON.parse(raw);
                this.contacts = data.contacts || [];
                this.messagesCache = data.messages || {};
            }
        } catch (e) {
            console.warn('Не удалось загрузить данные:', e);
        }
    }

    saveMediaLocally(msg) {
        try {
            // Сохраняем последние 50 медиафайлов
            const mediaKey = 'webchat_media';
            let media = JSON.parse(localStorage.getItem(mediaKey) || '[]');
            media.push({
                id: msg.id,
                fileName: msg.fileName,
                type: msg.messageType,
                timestamp: msg.timestamp
            });
            // Оставляем только последние 50
            if (media.length > 50) {
                media = media.slice(-50);
            }
            localStorage.setItem(mediaKey, JSON.stringify(media));
        } catch (e) {
            console.warn('Не удалось сохранить медиа:', e);
        }
    }

    cleanupOldData() {
        // Удаляем старые сообщения
        for (const key of Object.keys(this.messagesCache)) {
            const msgs = this.messagesCache[key];
            if (msgs.length > 100) {
                this.messagesCache[key] = msgs.slice(-100);
            }
            // Удаляем fileData у старых сообщений
            msgs.forEach(msg => {
                if (msg.fileData && msg.fileData.length > 100000) {
                    msg.fileData = ''; // Очищаем большие файлы
                }
            });
        }
        this.saveLocalData();
    }

    // ===== Утилиты =====

    formatTime(timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    }

    formatDate(timestamp) {
        const date = new Date(timestamp);
        const today = new Date();
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);

        if (date.toDateString() === today.toDateString()) return 'Сегодня';
        if (date.toDateString() === yesterday.toDateString()) return 'Вчера';
        return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    linkify(text) {
        const urlPattern = /(https?:\/\/[^\s<]+)/g;
        return text.replace(urlPattern, '<a href="$1" target="_blank" rel="noopener" style="color:#8b83ff;text-decoration:underline;">$1</a>');
    }

    scrollToBottom() {
        requestAnimationFrame(() => {
            const container = document.getElementById('messagesContainer');
            container.scrollTop = container.scrollHeight;
        });
    }

    playNotification() {
        try {
            // Вибрация
            if (navigator.vibrate) {
                navigator.vibrate(200);
            }

            // Звук
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioCtx.createOscillator();
            const gainNode = audioCtx.createGain();
            oscillator.connect(gainNode);
            gainNode.connect(audioCtx.destination);
            oscillator.frequency.value = 800;
            oscillator.type = 'sine';
            gainNode.gain.value = 0.1;
            oscillator.start();
            oscillator.stop(audioCtx.currentTime + 0.15);
        } catch (e) {
            // Ничего
        }
    }

    showNotification(msg) {
        if ('Notification' in window && Notification.permission === 'granted') {
            const notif = new Notification(`@${msg.from}`, {
                body: msg.messageType === 'text' ? msg.content : `📎 ${msg.fileName}`,
                icon: '💬',
                tag: msg.from,
                renotify: true
            });
            notif.onclick = () => {
                window.focus();
                this.openChat(msg.from);
                notif.close();
            };
        }
    }

    showToast(message, type = 'info') {
        const existing = document.querySelector('.toast');
        if (existing) existing.remove();

        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            padding: 12px 24px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 500;
            z-index: 10000;
            animation: slideDown 0.3s ease;
            color: white;
            background: ${type === 'error' ? 'var(--danger)' : type === 'success' ? 'var(--success)' : 'var(--accent)'};
            box-shadow: var(--shadow);
        `;
        toast.textContent = message;

        const style = document.createElement('style');
        style.textContent = `@keyframes slideDown { from { transform: translateX(-50%) translateY(-20px); opacity: 0; } to { transform: translateX(-50%) translateY(0); opacity: 1; } }`;
        document.head.appendChild(style);

        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    // ===== Привязка событий =====

    bindEvents() {
        // Логин
        document.getElementById('loginBtn').addEventListener('click', () => this.login());
        document.getElementById('nicknameInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.login();
        });

        // Поиск
        document.getElementById('searchBtn').addEventListener('click', () => {
            const panel = document.getElementById('searchPanel');
            panel.classList.toggle('hidden');
            if (!panel.classList.contains('hidden')) {
                document.getElementById('searchInput').focus();
            }
        });
        document.getElementById('searchCloseBtn').addEventListener('click', () => {
            document.getElementById('searchPanel').classList.add('hidden');
            document.getElementById('searchInput').value = '';
            document.getElementById('searchResults').innerHTML = '';
        });
        document.getElementById('searchGoBtn').addEventListener('click', () => this.searchUser());
        document.getElementById('searchInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.searchUser();
        });

        // Назад
        document.getElementById('backBtn').addEventListener('click', () => this.closeChat());

        // Отправка
        document.getElementById('sendBtn').addEventListener('click', () => this.sendMessage());

        const messageInput = document.getElementById('messageInput');
        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Авторесайз textarea
        messageInput.addEventListener('input', () => {
            messageInput.style.height = 'auto';
            messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
            this.sendTyping();
        });

        // Файлы
        document.getElementById('attachBtn').addEventListener('click', () => {
            document.getElementById('fileInput').click();
        });
        document.getElementById('fileInput').addEventListener('change', (e) => this.handleFileSelect(e));
        document.getElementById('filePreviewClose').addEventListener('click', () => this.clearFilePreview());

        // Медиа модальное окно
        document.getElementById('mediaModalClose').addEventListener('click', () => this.closeMedia());
        document.getElementById('mediaModal').addEventListener('click', (e) => {
            if (e.target === e.currentTarget) this.closeMedia();
        });

        // Скачать чат
        document.getElementById('downloadChatBtn').addEventListener('click', () => this.downloadChat());

        // Запрос уведомлений
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission();
        }

        // Настройки (выход)
        document.getElementById('settingsBtn').addEventListener('click', () => {
            if (confirm('Выйти из аккаунта?')) {
                localStorage.removeItem('webchat_nickname');
                location.reload();
            }
        });

        // Обработка Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (!document.getElementById('mediaModal').classList.contains('hidden')) {
                    this.closeMedia();
                } else if (document.getElementById('chatScreen').classList.contains('active') && window.innerWidth < 768) {
                    this.closeChat();
                }
            }
        });

        // Свайп назад на мобильном
        let touchStartX = 0;
        document.getElementById('chatScreen').addEventListener('touchstart', (e) => {
            touchStartX = e.touches[0].clientX;
        }, { passive: true });

        document.getElementById('chatScreen').addEventListener('touchend', (e) => {
            const touchEndX = e.changedTouches[0].clientX;
            const diff = touchEndX - touchStartX;
            if (diff > 100 && touchStartX < 50) {
                this.closeChat();
            }
        }, { passive: true });
    }
}

// Инициализация
const chat = new WebChat();
