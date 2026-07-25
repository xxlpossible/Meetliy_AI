/**
 * 多人会议页面逻辑
 * 功能：创建/加入会议、WebRTC Mesh 互听、实时 STT 转写（区分说话人）、
 *       会议结束触发音频合并转写、轮询纪要结果
 */

// ======================== 配置 ======================== //
// 页面通过后端 /test 挂载访问时（HTTP 协议，无论 localhost 还是局域网 IP），用相对路径同源访问
// 仅 file:// 直接打开时回退到 localhost
if (location.protocol.startsWith('http')) {
    var API_BASE = '';                              // 同源：相对路径
    var WS_BASE = 'ws://' + location.host;          // 同源：用当前 host（含局域网 IP）
} else {
    var API_BASE = 'http://localhost:31818';        // file:// 回退
    var WS_BASE = 'ws://localhost:31818';
}

// 说话人颜色调色板
const SPEAKER_COLORS = [
    '#e74c3c', '#3498db', '#2ecc71', '#9b59b6',
    '#f39c12', '#1abc9c', '#e67e22', '#34495e',
];

// ======================== 状态 ======================== //

let accessToken = localStorage.getItem('access_token');
let username = localStorage.getItem('username') || '-';
let myUserId = null;
let currentMeetingId = null;
let isHost = false;

let ws = null;
let mediaStream = null;
let audioContext = null;
let processor = null;
let micEnabled = true;

let peerConnections = new Map(); // userId -> RTCPeerConnection
let pendingCandidates = new Map(); // userId -> [RTCIceCandidateInit, ...] 缓存早于 setRemoteDescription 到达的 ICE 候选
let participants = new Map();    // userId -> {id, name}

let finalTranscripts = [];
let interimBySpeaker = new Map();
let speakingSpeakers = new Set();

let pollTimer = null;

// ======================== 初始化 ======================== //

document.addEventListener('DOMContentLoaded', () => {
    // 鉴权守卫
    if (!accessToken) {
        location.href = 'login.html';
        return;
    }

    // 解析 user_id
    try {
        const payload = JSON.parse(atob(accessToken.split('.')[1]));
        myUserId = payload.user_id;
    } catch (e) {
        alert('Token 解析失败，请重新登录');
        location.href = 'login.html';
        return;
    }

    document.getElementById('currentUsername').textContent = username;

    document.getElementById('logoutBtn').addEventListener('click', logout);
    document.getElementById('createMeetingBtn').addEventListener('click', createMeeting);
    document.getElementById('joinMeetingBtn').addEventListener('click', joinMeeting);
    document.getElementById('endMeetingBtn').addEventListener('click', endMeeting);
    document.getElementById('leaveMeetingBtn').addEventListener('click', leaveMeeting);
    document.getElementById('micToggleBtn').addEventListener('click', toggleMic);
});

function logout() {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('username');
    location.href = 'login.html';
}

// ======================== 创建/加入会议 ======================== //

async function createMeeting() {
    const meetingName = document.getElementById('meetingNameInput').value.trim();
    const btn = document.getElementById('createMeetingBtn');
    btn.disabled = true;
    btn.textContent = '创建中...';

    try {
        const resp = await fetch(`${API_BASE}/api/v1/meeting/create`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${accessToken}`,
            },
            body: JSON.stringify({ meeting_name: meetingName || null }),
        });
        const data = await resp.json();
        if (resp.ok && data.status_code === 200) {
            currentMeetingId = data.data.meeting_id;
            isHost = true;
            enterMeeting(data.data.meeting_name, []);
        } else {
            alert(data.detail || data.status_message || '创建失败');
        }
    } catch (e) {
        alert(`网络错误: ${e.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = '创建会议';
    }
}

async function joinMeeting() {
    const meetingId = document.getElementById('meetingIdInput').value.trim();
    if (!meetingId) {
        alert('请输入会议ID');
        return;
    }

    const btn = document.getElementById('joinMeetingBtn');
    btn.disabled = true;
    btn.textContent = '加入中...';

    try {
        const resp = await fetch(`${API_BASE}/api/v1/meeting/${meetingId}/join`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${accessToken}`,
            },
        });
        const data = await resp.json();
        if (resp.ok && data.status_code === 200) {
            currentMeetingId = meetingId;
            isHost = data.data.is_host;
            enterMeeting(data.data.meeting_name, data.data.participants || []);
        } else {
            alert(data.detail || data.status_message || '加入失败');
        }
    } catch (e) {
        alert(`网络错误: ${e.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = '加入会议';
    }
}

// ======================== 进入会议 ======================== //

async function enterMeeting(meetingName, existingParticipants) {
    document.getElementById('lobbyView').style.display = 'none';
    document.getElementById('meetingView').classList.add('active');
    document.getElementById('currentMeetingId').textContent = currentMeetingId;
    document.getElementById('meetingTitle').textContent = meetingName || '会议中';

    if (isHost) {
        document.getElementById('endMeetingBtn').style.display = 'inline-block';
    }

    // 初始化参与者列表（排除自己）
    participants.clear();
    existingParticipants.forEach(p => {
        if (p.id !== myUserId) {
            participants.set(p.id, p);
        }
    });
    renderParticipants();

    try {
        // 1. 启动麦克风
        await startMicrophone();

        // 2. 连接 STT WebSocket
        // WebRTC 发起不在此时做——因为 WS 尚未 open，sendSignal 会丢弃 offer。
        // WebRTC 发起由 WS 连上后收到的 participants_list 回调(handleParticipantsList)处理，
        // 以及后续其他参会者加入时的 participant_joined 回调(handleParticipantJoined)处理。
        // 这两个回调触发时 WS 必然已 open，sendSignal 不会丢消息。
        connectWebSocket();
    } catch (e) {
        alert(`初始化失败: ${e.message}`);
    }
}

// ======================== 麦克风 ======================== //

async function startMicrophone() {
    // 安全上下文检查：getUserMedia 和 WebRTC 需要 HTTPS 或 localhost
    if (!window.isSecureContext) {
        throw new Error(
            '当前页面非安全上下文，浏览器禁止访问麦克风。\n\n' +
            '解决方法（任选其一）：\n' +
            '1. 在本机用 localhost 访问：http://localhost:31818/test/meeting.html\n' +
            '2. Chrome 地址栏输入 chrome://flags/#unsafely-treat-insecure-origin-as-secure，\n' +
            '   添加 http://你的IP:31818 并启用，重启浏览器\n' +
            '3. 给后端配置 HTTPS 证书'
        );
    }

    mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
            channelCount: 1,
            sampleRate: 16000,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
        }
    });

    audioContext = new AudioContext({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(mediaStream);
    const bufferSize = 4096;
    processor = audioContext.createScriptProcessor(bufferSize, 1, 1);

    processor.onaudioprocess = (e) => {
        if (!micEnabled) return;
        const inputData = e.inputBuffer.getChannelData(0);
        const pcmData = float32ToInt16(inputData);
        if (ws && ws.readyState === WebSocket.OPEN) {
            const blob = new Blob([pcmData.buffer], { type: 'application/octet-stream' });
            ws.send(blob);
        }
    };

    source.connect(processor);
    processor.connect(audioContext.destination);

    micEnabled = true;
    updateStatus('micStatus', '麦克风: 开启', 'connected');
    document.getElementById('micToggleBtn').textContent = '关闭麦克风';
}

function toggleMic() {
    micEnabled = !micEnabled;
    if (mediaStream) {
        mediaStream.getAudioTracks().forEach(t => t.enabled = micEnabled);
    }
    updateStatus('micStatus', micEnabled ? '麦克风: 开启' : '麦克风: 静音', micEnabled ? 'connected' : 'disconnected');
    document.getElementById('micToggleBtn').textContent = micEnabled ? '关闭麦克风' : '开启麦克风';
}

function float32ToInt16(float32Array) {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
        const s = Math.max(-1, Math.min(1, float32Array[i]));
        int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16Array;
}

// ======================== WebSocket ======================== //

function connectWebSocket() {
    const wsUrl = `${WS_BASE}/api/v1/audio/ws/realtime?meeting_id=${encodeURIComponent(currentMeetingId)}&token=${encodeURIComponent(accessToken)}`;

    ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
        console.log('[WS] 连接已建立，等待 participants_list...');
        updateStatus('wsStatus', 'WS: 已连接', 'connected');
    };

    ws.onmessage = (event) => {
        // 只处理文本消息（JSON），二进制是回声不需处理
        if (typeof event.data === 'string') {
            handleMessage(JSON.parse(event.data));
        }
    };

    ws.onclose = (event) => {
        updateStatus('wsStatus', `WS: 已断开 (${event.code})`, 'disconnected');
        if (event.code === 4401) {
            alert('认证失败，请重新登录');
            logout();
        }
    };

    ws.onerror = () => {
        updateStatus('wsStatus', 'WS: 错误', 'disconnected');
    };
}

function handleMessage(msg) {
    switch (msg.type) {
        case 'transcript':
            handleTranscript(msg);
            break;
        case 'signal':
            handleSignal(msg);
            break;
        case 'participants_list':
            handleParticipantsList(msg.participants || []);
            break;
        case 'participant_joined':
            handleParticipantJoined(msg.user);
            break;
        case 'participant_left':
            handleParticipantLeft(msg.user);
            break;
        case 'speech_started':
            speakingSpeakers.add(msg.speaker_id);
            renderParticipants();
            break;
        case 'speech_stopped':
            speakingSpeakers.delete(msg.speaker_id);
            renderParticipants();
            break;
        case 'meeting_ended':
            handleMeetingEnded(msg.task_id);
            break;
    }
}

// ======================== 转写显示 ======================== //

function handleTranscript(msg) {
    const { speaker_id, speaker_name, text, is_final } = msg;

    if (is_final) {
        finalTranscripts.push({
            speaker_id,
            speaker_name,
            text,
            time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
        });
        interimBySpeaker.delete(speaker_id);
    } else {
        interimBySpeaker.set(speaker_id, { speaker_name, text });
    }
    renderTranscript();
}

function renderTranscript() {
    const area = document.getElementById('transcriptArea');
    let html = '';

    if (finalTranscripts.length === 0 && interimBySpeaker.size === 0) {
        area.innerHTML = '<p class="placeholder">等待参会者发言...</p>';
        return;
    }

    for (const t of finalTranscripts) {
        const color = getSpeakerColor(t.speaker_id);
        html += `<div class="transcript-line">
            <span class="time">${t.time}</span>
            <span class="speaker" style="color:${color}">${escapeHtml(t.speaker_name)}:</span>
            <span class="text">${escapeHtml(t.text)}</span>
        </div>`;
    }

    for (const [speakerId, info] of interimBySpeaker) {
        const color = getSpeakerColor(speakerId);
        html += `<div class="transcript-line interim">
            <span class="time"></span>
            <span class="speaker" style="color:${color}">${escapeHtml(info.speaker_name)}:</span>
            <span class="text">${escapeHtml(info.text)}</span>
        </div>`;
    }

    area.innerHTML = html;
    area.scrollTop = area.scrollHeight;
}

function getSpeakerColor(userId) {
    return SPEAKER_COLORS[userId % SPEAKER_COLORS.length];
}

// ======================== 参与者 ======================== //

function renderParticipants() {
    const list = document.getElementById('participantsList');
    let html = `<div class="participant-chip ${isHost ? 'host' : ''}">
        <span class="speaking-dot"></span>${escapeHtml(username)}（我）${isHost ? ' 👑' : ''}
    </div>`;

    for (const [uid, p] of participants) {
        const speaking = speakingSpeakers.has(uid);
        const isChipHost = false; // 简化：只有自己标 host
        html += `<div class="participant-chip ${speaking ? 'speaking' : ''}">
            <span class="speaking-dot"></span>${escapeHtml(p.name)}
        </div>`;
    }

    list.innerHTML = html;
}

function handleParticipantsList(list) {
    // WS 连接后收到当前房间已有参与者列表（解决竞态）
    list.forEach(p => {
        if (p.id !== myUserId) {
            participants.set(p.id, p);
            // 用 userId 大小避免 glare：较小者主动发起 offer
            if (!peerConnections.has(p.id) && myUserId < p.id) {
                initiateWebRTC(p.id);
            }
        }
    });
    renderParticipants();
}

function handleParticipantJoined(user) {
    if (user.id === myUserId) return;
    if (!participants.has(user.id)) {
        participants.set(user.id, user);
        renderParticipants();
    }
    // 用 userId 大小避免 glare：较小者主动发起 offer
    if (!peerConnections.has(user.id) && myUserId < user.id) {
        initiateWebRTC(user.id);
    }
}

function handleParticipantLeft(user) {
    participants.delete(user.id);
    // 关闭对应的 PeerConnection
    const pc = peerConnections.get(user.id);
    if (pc) {
        pc.close();
        peerConnections.delete(user.id);
    }
    pendingCandidates.delete(user.id);
    // 移除远程音频元素
    const audioEl = document.getElementById(`remote-audio-${user.id}`);
    if (audioEl) audioEl.remove();

    renderParticipants();
    updateWebRTCStatus();
}

// ======================== WebRTC Mesh ======================== //

const RTC_CONFIG = {
    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
};

function initiateWebRTC(targetUserId) {
    if (peerConnections.has(targetUserId)) return;
    createPeerConnection(targetUserId, true);
}

function createPeerConnection(targetUserId, isInitiator = false) {
    const pc = new RTCPeerConnection(RTC_CONFIG);
    peerConnections.set(targetUserId, pc);

    // 先设置所有事件处理器，再添加轨道（确保 onnegotiationneeded 不丢失）
    if (isInitiator) {
        pc.onnegotiationneeded = async () => {
            try {
                console.log(`[WebRTC] onnegotiationneeded 触发: user=${targetUserId}`);
                const offer = await pc.createOffer();
                await pc.setLocalDescription(offer);
                sendSignal(targetUserId, 'offer', offer);
            } catch (e) {
                console.error(`[WebRTC] 创建 offer 失败: user=${targetUserId}, ${e.message}`);
            }
        };
    }

    // 接收远程音频
    pc.ontrack = (event) => {
        console.log(`[WebRTC] 收到远程轨道: user=${targetUserId}, streams=${event.streams.length}, tracks=${event.streams[0]?.getTracks().length}`);
        let audioEl = document.getElementById(`remote-audio-${targetUserId}`);
        if (!audioEl) {
            audioEl = document.createElement('audio');
            audioEl.id = `remote-audio-${targetUserId}`;
            audioEl.autoplay = true;
            audioEl.controls = false;
            document.getElementById('remoteAudioContainer').appendChild(audioEl);
        }
        audioEl.srcObject = event.streams[0];
        // 确保自动播放（某些浏览器需要显式 play）
        audioEl.play().catch(e => console.warn(`[WebRTC] 音频自动播放被阻止: ${e.message}`));
    };

    // ICE 候选
    pc.onicecandidate = (event) => {
        if (event.candidate) {
            console.log(`[WebRTC] 生成 ICE 候选: user=${targetUserId}, candidate=${event.candidate.candidate.substring(0, 60)}...`);
            sendSignal(targetUserId, 'ice', event.candidate);
        } else {
            console.log(`[WebRTC] ICE 候选收集完毕: user=${targetUserId}`);
        }
    };

    pc.oniceconnectionstatechange = () => {
        console.log(`[WebRTC] ICE 连接状态: user=${targetUserId}, state=${pc.iceConnectionState}`);
        updateWebRTCStatus();
    };

    pc.onconnectionstatechange = () => {
        console.log(`[WebRTC] 连接状态: user=${targetUserId}, state=${pc.connectionState}`);
        updateWebRTCStatus();
    };

    // 添加本地音频轨（在所有 handler 设置完成后）
    if (mediaStream) {
        mediaStream.getAudioTracks().forEach(track => {
            pc.addTrack(track, mediaStream);
        });
        console.log(`[WebRTC] 已添加本地音频轨到 PC(${targetUserId}), tracks=${mediaStream.getAudioTracks().length}`);
    } else {
        console.warn(`[WebRTC] mediaStream 为空，未添加本地音频轨到 PC(${targetUserId})`);
    }

    return pc;
}

function sendSignal(toUserId, signalType, data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            to_user_id: toUserId,
            signal_type: signalType,
            data: data,
        }));
    } else {
        console.warn(`[WebRTC] sendSignal 失败: WS 未连接 (readyState=${ws?.readyState}), to=${toUserId}, type=${signalType}`);
    }
}

async function handleSignal(msg) {
    const fromUserId = msg.from;
    const signalType = msg.signal_type;
    const data = msg.data;

    let pc = peerConnections.get(fromUserId);

    if (signalType === 'offer') {
        // 收到 offer：创建 PC（如不存在），设远程描述，创建 answer
        if (!pc) {
            pc = createPeerConnection(fromUserId, false);  // 非发起方，不设 onnegotiationneeded
            if (!participants.has(fromUserId)) {
                participants.set(fromUserId, { id: fromUserId, name: msg.from_name || `用户${fromUserId}` });
                renderParticipants();
            }
        }
        console.log(`[WebRTC] 收到 offer: user=${fromUserId}`);
        await pc.setRemoteDescription(new RTCSessionDescription(data));
        console.log(`[WebRTC] 远程描述已设置(offer): user=${fromUserId}`);
        // 刷新此前缓存的 ICE 候选
        await flushPendingCandidates(fromUserId, pc);

        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        console.log(`[WebRTC] 发送 answer: user=${fromUserId}`);
        sendSignal(fromUserId, 'answer', answer);

    } else if (signalType === 'answer') {
        // 收到 answer：设远程描述
        if (pc) {
            console.log(`[WebRTC] 收到 answer: user=${fromUserId}`);
            await pc.setRemoteDescription(new RTCSessionDescription(data));
            console.log(`[WebRTC] 远程描述已设置(answer): user=${fromUserId}`);
            // 刷新此前缓存的 ICE 候选
            await flushPendingCandidates(fromUserId, pc);
        }

    } else if (signalType === 'ice') {
        // 收到 ICE 候选
        if (pc && pc.remoteDescription) {
            // 远程描述已设置，直接添加
            try {
                await pc.addIceCandidate(new RTCIceCandidate(data));
                console.log(`[WebRTC] ICE 候选已添加: user=${fromUserId}`);
            } catch (e) {
                console.warn(`[WebRTC] 添加 ICE 候选失败: user=${fromUserId}, ${e.message}`);
            }
        } else {
            // 远程描述尚未设置（offer/answer 还在处理中），缓存候选取
            if (!pendingCandidates.has(fromUserId)) {
                pendingCandidates.set(fromUserId, []);
            }
            pendingCandidates.get(fromUserId).push(data);
            console.log(`[WebRTC] 缓存 ICE 候选(等待远程描述): user=${fromUserId}, 缓存数=${pendingCandidates.get(fromUserId).length}`);
        }
    }
}

async function flushPendingCandidates(userId, pc) {
    const buffered = pendingCandidates.get(userId);
    if (!buffered || buffered.length === 0) return;
    console.log(`[WebRTC] 刷新 ${buffered.length} 个缓存的 ICE 候选: user=${userId}`);
    for (const candidate of buffered) {
        try {
            await pc.addIceCandidate(new RTCIceCandidate(candidate));
        } catch (e) {
            console.warn(`[WebRTC] 刷新时添加 ICE 候选失败: user=${userId}, ${e.message}`);
        }
    }
    pendingCandidates.delete(userId);
}

function updateWebRTCStatus() {
    let connectedCount = 0;
    let connectingCount = 0;
    for (const [uid, pc] of peerConnections) {
        const iceState = pc.iceConnectionState;
        const connState = pc.connectionState;
        // iceConnectionState 更新更及时，connected/checking 都说明有进展
        if (iceState === 'connected' || iceState === 'completed' || connState === 'connected') {
            connectedCount++;
        } else if (iceState === 'checking' || connState === 'connecting') {
            connectingCount++;
        }
    }
    if (connectedCount > 0) {
        updateStatus('webrtcStatus', `WebRTC: ${connectedCount} 路已连接`, 'connected');
    } else if (connectingCount > 0) {
        updateStatus('webrtcStatus', `WebRTC: 连接中(${connectingCount})`, 'recording');
    } else {
        updateStatus('webrtcStatus', 'WebRTC: 未连接', 'disconnected');
    }
}

// ======================== 结束/离开会议 ======================== //

async function endMeeting() {
    if (!confirm('确定要结束会议吗？将自动合并录音并生成会议纪要。')) return;

    const btn = document.getElementById('endMeetingBtn');
    btn.disabled = true;
    btn.textContent = '结束中...';

    try {
        const resp = await fetch(`${API_BASE}/api/v1/meeting/${currentMeetingId}/end`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${accessToken}` },
        });
        const data = await resp.json();
        if (resp.ok && data.status_code === 200) {
            const taskId = data.data.task_id;
            showResultArea('会议已结束，正在生成纪要...');
            startPolling(taskId);
        } else {
            alert(data.detail || data.status_message || '结束失败');
        }
    } catch (e) {
        alert(`网络错误: ${e.message}`);
    } finally {
        btn.disabled = false;
        btn.textContent = '结束会议';
    }
}

function handleMeetingEnded(taskId) {
    showResultArea('主持人已结束会议，正在生成纪要...');
    startPolling(taskId);
}

function showResultArea(text) {
    const area = document.getElementById('resultArea');
    area.classList.add('show');
    document.getElementById('resultText').innerHTML = `<span class="loading-spinner"></span>${text}`;
}

function startPolling(taskId) {
    if (pollTimer) clearInterval(pollTimer);

    let attempts = 0;
    const maxAttempts = 120; // 10分钟（每5秒一次）

    pollTimer = setInterval(async () => {
        attempts++;
        if (attempts > maxAttempts) {
            clearInterval(pollTimer);
            document.getElementById('resultText').innerHTML = '超时，请稍后在转录列表中查看结果。';
            return;
        }

        try {
            const resp = await fetch(`${API_BASE}/api/v1/audio/getTask/status`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${accessToken}`,
                },
                body: JSON.stringify([taskId]),
            });
            const data = await resp.json();
            if (resp.ok && data.status_code === 200) {
                const tasks = data.data || [];
                const task = tasks.find(t => t.id === taskId);
                if (task && task.status === 1) {
                    clearInterval(pollTimer);
                    displayResult(taskId, task.result);
                }
            }
        } catch (e) {
            console.warn('轮询失败:', e.message);
        }
    }, 5000);
}

function displayResult(taskId, result) {
    const area = document.getElementById('resultArea');
    let html = '<h3>会议纪要已生成</h3>';
    html += `<p style="margin-top:8px;color:#555;">转录任务ID: ${escapeHtml(taskId)}</p>`;

    if (result && typeof result === 'object') {
        // 尝试展示结果的摘要
        const text = JSON.stringify(result, null, 2);
        if (text.length < 5000) {
            html += `<pre style="margin-top:10px;background:#f8f8f8;padding:12px;border-radius:6px;font-size:0.8em;overflow-x:auto;max-height:300px;">${escapeHtml(text)}</pre>`;
        } else {
            html += `<p style="margin-top:8px;">结果数据较大，请在转录列表中查看完整内容。</p>`;
        }
    }

    html += `<p style="margin-top:12px;"><a href="${API_BASE}/test/index.html" style="color:#667eea;">返回大厅</a></p>`;
    document.getElementById('resultText').innerHTML = html;
}

function leaveMeeting() {
    if (!confirm('确定要离开会议吗？')) return;

    // 关闭 WS
    if (ws) {
        ws.close();
        ws = null;
    }

    // 关闭所有 PeerConnection
    for (const [uid, pc] of peerConnections) {
        pc.close();
        const audioEl = document.getElementById(`remote-audio-${uid}`);
        if (audioEl) audioEl.remove();
    }
    peerConnections.clear();
    pendingCandidates.clear();

    // 停止麦克风
    if (processor) { processor.disconnect(); processor = null; }
    if (audioContext) { audioContext.close(); audioContext = null; }
    if (mediaStream) {
        mediaStream.getTracks().forEach(t => t.stop());
        mediaStream = null;
    }

    // 停止轮询
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

    // 回到大厅
    location.reload();
}

// ======================== 工具函数 ======================== //

function updateStatus(elementId, text, statusClass) {
    const el = document.getElementById(elementId);
    el.textContent = text;
    el.className = `status-badge status-${statusClass}`;
}

function escapeHtml(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}
