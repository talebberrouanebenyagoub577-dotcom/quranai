(function () {
    "use strict";

    const LEGACY_STORAGE_KEY = "sahra_conversations";
    const LEGACY_ACTIVE_KEY = "sahra_active_chat";

    const $ = (s) => document.querySelector(s);

    const sidebar      = $("#sidebar");
    const overlay      = $("#overlay");
    const chatArea     = $("#chatArea");
    const messagesEl   = $("#messages");
    const welcome      = $("#welcomeScreen");
    const historyEl    = $("#chatHistory");
    const form         = $("#chatForm");
    const input        = $("#messageInput");
    const sendBtn      = $("#sendBtn");

    let chats = [];
    let activeId = null;
    let busy = false;
    let ready = false;

    const AMAZON_PATTERNS = [
        /https?:\/\/(?:www\.)?amazon\.[a-z.]{2,15}\/[^\s<>"'\]]+/i,
        /https?:\/\/(?:www\.)?amzn\.[a-z.]{2,12}\/[^\s<>"'\]]+/i,
        /https?:\/\/a\.co\/[^\s<>"'\]]+/i,
        /(?:https?:\/\/)?(?:www\.)?amazon\.[a-z.]{2,15}\/(?:dp|gp\/product|gp\/aw\/d)\/[^\s<>"'\]]+/i,
    ];

    function extractAmazonUrl(text) {
        const cleaned = (text || "").trim().replace(/[\u200e\u200f]/g, "");
        for (const pattern of AMAZON_PATTERNS) {
            const match = cleaned.match(pattern);
            if (match) {
                let url = match[0].replace(/[.,;:!?)\]}>"']+$/, "");
                if (!/^https?:\/\//i.test(url)) {
                    url = "https://" + url.replace(/^\/+/, "");
                }
                return url;
            }
        }
        return null;
    }

    function isAmazonMessage(text) {
        return extractAmazonUrl(text) !== null;
    }

    async function apiRequest(url, options = {}) {
        const res = await fetch(url, {
            headers: { "Content-Type": "application/json; charset=utf-8" },
            ...options,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            throw new Error(data.error || "حدث خطأ في الخادم");
        }
        return data;
    }

    function loadLegacyChats() {
        try {
            const data = JSON.parse(localStorage.getItem(LEGACY_STORAGE_KEY));
            return Array.isArray(data) ? data : [];
        } catch {
            return [];
        }
    }

    function clearLegacyStorage() {
        localStorage.removeItem(LEGACY_STORAGE_KEY);
        localStorage.removeItem(LEGACY_ACTIVE_KEY);
    }

    async function migrateLegacyChatsIfNeeded() {
        const legacyChats = loadLegacyChats();
        if (!legacyChats.length) {
            return;
        }

        const activeLegacy = localStorage.getItem(LEGACY_ACTIVE_KEY) || null;
        const data = await apiRequest("/api/conversations/import", {
            method: "POST",
            body: JSON.stringify({
                conversations: legacyChats,
                active_id: activeLegacy,
            }),
        });

        if (data.imported > 0) {
            clearLegacyStorage();
        }
    }

    async function loadChatsFromServer() {
        await migrateLegacyChatsIfNeeded();
        const data = await apiRequest("/api/conversations");
        chats = Array.isArray(data.conversations) ? data.conversations : [];
        activeId = data.active_id || null;
    }

    function active() {
        return chats.find((c) => c.id === activeId) || null;
    }

    function sortChats() {
        chats.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
    }

    async function persistActive() {
        await apiRequest("/api/conversations/active", {
            method: "PUT",
            body: JSON.stringify({ active_id: activeId }),
        });
    }

    async function persistConversation(conversation) {
        if (!conversation) return;
        const updated = await apiRequest(`/api/conversations/${conversation.id}`, {
            method: "PUT",
            body: JSON.stringify({
                title: conversation.title,
                messages: conversation.messages,
                updatedAt: conversation.updatedAt,
            }),
        });
        const index = chats.findIndex((c) => c.id === conversation.id);
        if (index >= 0) {
            chats[index] = updated;
        }
        sortChats();
    }

    async function newChat(firstQ) {
        const title = firstQ.length > 40 ? firstQ.slice(0, 40) + "…" : firstQ;
        const created = await apiRequest("/api/conversations", {
            method: "POST",
            body: JSON.stringify({ title, messages: [] }),
        });
        chats.unshift(created);
        activeId = created.id;
        sortChats();
        return created;
    }

    /* ── History sidebar ── */
    function renderHistory() {
        historyEl.innerHTML = "";
        if (!ready) {
            historyEl.innerHTML = '<p class="history-empty">جاري تحميل المحادثات...</p>';
            return;
        }
        if (!chats.length) {
            historyEl.innerHTML = '<p class="history-empty">لا توجد محادثات بعد</p>';
            return;
        }

        chats.forEach((c) => {
            const el = document.createElement("div");
            el.className = "history-item" + (c.id === activeId ? " active" : "");
            el.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
                </svg>
                <span></span>
                <div class="history-actions">
                    <button class="history-rename" title="إعادة تسمية">✎</button>
                    <button class="history-del" title="حذف">✕</button>
                </div>`;
            el.querySelector("span").textContent = c.title;
            el.addEventListener("click", () => openChat(c.id));
            el.querySelector(".history-rename").addEventListener("click", (e) => {
                e.stopPropagation();
                renameChat(c.id);
            });
            el.querySelector(".history-del").addEventListener("click", (e) => {
                e.stopPropagation();
                deleteChat(c.id);
            });
            historyEl.appendChild(el);
        });
    }

    async function openChat(id) {
        activeId = id;
        await persistActive();
        renderHistory();
        renderMessages();
        closeMobileSidebar();
    }

    async function renameChat(id) {
        const chat = chats.find((c) => c.id === id);
        if (!chat) return;

        const nextTitle = prompt("اسم المحادثة:", chat.title);
        if (nextTitle === null) return;

        const cleaned = nextTitle.trim();
        if (!cleaned) {
            alert("عنوان المحادثة فارغ");
            return;
        }

        try {
            const updated = await apiRequest(`/api/conversations/${id}/rename`, {
                method: "PUT",
                body: JSON.stringify({ title: cleaned }),
            });
            const index = chats.findIndex((c) => c.id === id);
            if (index >= 0) {
                chats[index] = updated;
            }
            sortChats();
            renderHistory();
        } catch (err) {
            alert(err.message || "تعذر إعادة تسمية المحادثة");
        }
    }

    async function deleteChat(id) {
        if (!confirm("حذف هذه المحادثة؟")) return;

        try {
            const result = await apiRequest(`/api/conversations/${id}`, {
                method: "DELETE",
            });
            chats = chats.filter((c) => c.id !== id);
            activeId = result.active_id || null;
            renderHistory();
            renderMessages();
        } catch (err) {
            alert(err.message || "تعذر حذف المحادثة");
        }
    }

    /* ── Messages ── */
    function renderMessages() {
        messagesEl.innerHTML = "";
        const c = active();
        if (!c || !c.messages.length) {
            welcome.classList.remove("hidden");
            return;
        }
        welcome.classList.add("hidden");
        c.messages.forEach((m) => addMsgDOM(m.role, m.content, false));
        scrollBottom();
    }

    function addMsgDOM(role, text, animate) {
        welcome.classList.add("hidden");

        const row = document.createElement("div");
        row.className = "msg-row " + role;

        const inner = document.createElement("div");
        inner.className = "msg-inner";

        const av = document.createElement("div");
        av.className = "msg-avatar " + (role === "user" ? "user" : "ai");
        av.textContent = role === "user" ? "أ" : "ص";

        const content = document.createElement("div");
        content.className = "msg-content";

        if (role === "assistant" && animate) {
            typeWrite(content, text);
        } else {
            content.textContent = text;
        }

        const body = document.createElement("div");
        body.style.flex = "1";
        body.style.minWidth = "0";
        body.appendChild(content);

        if (role === "assistant") {
            const actions = document.createElement("div");
            actions.className = "msg-actions";
            const copyBtn = document.createElement("button");
            copyBtn.className = "action-btn";
            copyBtn.textContent = "نسخ";
            copyBtn.addEventListener("click", () => {
                navigator.clipboard.writeText(text).then(() => {
                    copyBtn.textContent = "✓ تم النسخ";
                    copyBtn.classList.add("done");
                    setTimeout(() => {
                        copyBtn.textContent = "نسخ";
                        copyBtn.classList.remove("done");
                    }, 2000);
                });
            });
            actions.appendChild(copyBtn);
            body.appendChild(actions);
        }

        inner.appendChild(av);
        inner.appendChild(body);
        row.appendChild(inner);
        messagesEl.appendChild(row);
        scrollBottom();
    }

    function typeWrite(el, text) {
        el.textContent = "";
        let i = 0;
        (function tick() {
            if (i < text.length) {
                el.textContent += text[i++];
                scrollBottom();
                setTimeout(tick, 8);
            }
        })();
    }

    function showThinking() {
        const row = document.createElement("div");
        row.className = "typing-row";
        row.id = "thinking";
        row.innerHTML = `
            <div class="typing-inner">
                <div class="msg-avatar ai">ص</div>
                <span class="typing-text">صحرا يفكر...</span>
                <div class="typing-dots"><i></i><i></i><i></i></div>
            </div>`;
        messagesEl.appendChild(row);
        scrollBottom();
    }

    function hideThinking() {
        $("#thinking")?.remove();
    }

    function scrollBottom() {
        requestAnimationFrame(() => {
            chatArea.scrollTop = chatArea.scrollHeight;
        });
    }

    /* ── Send ── */
    async function send(text) {
        const q = text.trim();
        if (!q || busy || !ready) return;

        const amazonUrl = extractAmazonUrl(q);
        const productMode = amazonUrl !== null;

        let c = active();
        if (!c) {
            c = await newChat(q);
            renderHistory();
        }

        c.messages.push({ role: "user", content: q });
        c.updatedAt = Date.now();
        await persistConversation(c);
        addMsgDOM("user", q, false);

        input.value = "";
        resizeInput();
        updateSendBtn();
        busy = true;
        sendBtn.disabled = true;
        showThinking();

        try {
            const payload = {
                question: q,
                url: amazonUrl || "",
            };

            console.log("[Sahra] send", productMode ? "product" : "law", amazonUrl || q.slice(0, 80));

            const res = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json; charset=utf-8" },
                body: JSON.stringify(payload),
            });
            const data = await res.json();
            hideThinking();
            if (!res.ok) throw new Error(data.error || "حدث خطأ");

            console.log("[Sahra] mode:", data.mode, "amazon_url:", data.amazon_url || "none");

            c.messages.push({ role: "assistant", content: data.answer });
            c.updatedAt = Date.now();
            await persistConversation(c);
            sortChats();
            renderHistory();
            addMsgDOM("assistant", data.answer, true);
        } catch (err) {
            hideThinking();
            addMsgDOM("assistant", err.message || "خطأ في الاتصال", false);
        } finally {
            busy = false;
            sendBtn.disabled = false;
            updateSendBtn();
            input.focus();
        }
    }

    /* ── UI helpers ── */
    function resizeInput() {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 200) + "px";
    }

    function updateSendBtn() {
        const has = input.value.trim().length > 0;
        sendBtn.classList.toggle("active", has && !busy && ready);
        sendBtn.disabled = !has || busy || !ready;
    }

    async function startNewChat() {
        activeId = null;
        await persistActive();
        messagesEl.innerHTML = "";
        welcome.classList.remove("hidden");
        renderHistory();
        input.focus();
        closeMobileSidebar();
    }

    async function clearCurrent() {
        if (!activeId) return;
        await deleteChat(activeId);
        if (!activeId) {
            messagesEl.innerHTML = "";
            welcome.classList.remove("hidden");
        }
    }

    function closeMobileSidebar() {
        sidebar.classList.remove("mobile-open");
        overlay.classList.remove("open");
    }

    /* ── Events ── */
    $("#newChatBtn").addEventListener("click", () => {
        startNewChat().catch((err) => alert(err.message || "تعذر بدء محادثة جديدة"));
    });
    $("#clearChatBtn").addEventListener("click", () => {
        clearCurrent().catch((err) => alert(err.message || "تعذر مسح المحادثة"));
    });
    $("#menuBtn").addEventListener("click", () => {
        sidebar.classList.add("mobile-open");
        overlay.classList.add("open");
    });
    overlay.addEventListener("click", closeMobileSidebar);

    $("#sidebarToggle").addEventListener("click", () => {
        sidebar.classList.toggle("collapsed");
    });

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        send(input.value).catch((err) => alert(err.message || "تعذر إرسال الرسالة"));
    });

    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send(input.value).catch((err) => alert(err.message || "تعذر إرسال الرسالة"));
        }
    });

    input.addEventListener("input", () => {
        resizeInput();
        updateSendBtn();
    });

    document.querySelectorAll(".chip").forEach((b) =>
        b.addEventListener("click", () => {
            send(b.dataset.q).catch((err) => alert(err.message || "تعذر إرسال الرسالة"));
        })
    );

    function setupPhoneAccess() {
        const phoneAccess = $("#phoneAccess");
        const phoneUrl = $("#phoneUrl");
        if (!phoneAccess || !phoneUrl) return;

        const isMobile = window.matchMedia("(max-width: 768px)").matches
            || /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
        const host = window.location.hostname;

        if (isMobile && (host === "127.0.0.1" || host === "localhost")) {
            phoneAccess.style.display = "block";
            phoneAccess.querySelector(".phone-access-title").textContent = "تنبيه: هذا العنوان لا يعمل على الهاتف";
            phoneAccess.querySelector(".phone-access-note").textContent =
                "استخدم عنوان IP الكمبيوتر من نفس شبكة الواي فاي، مثل http://192.168.1.6:5000";
            return;
        }

        if (isMobile) {
            phoneAccess.style.display = "none";
            return;
        }

        fetch("/api/server-info")
            .then((res) => res.json())
            .then((data) => {
                if (!data.phone_url) return;
                phoneUrl.textContent = data.phone_url;
                phoneUrl.href = data.phone_url;
            })
            .catch(() => {});
    }

    /* ── Init ── */
    async function init() {
        setupPhoneAccess();
        renderHistory();
        try {
            await loadChatsFromServer();
            ready = true;
            renderHistory();
            if (activeId && active()) {
                renderMessages();
            }
        } catch (err) {
            ready = false;
            historyEl.innerHTML = `<p class="history-empty">${err.message || "تعذر تحميل المحادثات"}</p>`;
        } finally {
            updateSendBtn();
            input.focus();
        }
    }

    init();
})();
