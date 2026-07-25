/**
 * 实时语音转文字测试 - 前端逻辑
 * 功能：通过 WebSocket 连接后端，使用麦克风录音并实时获取转写结果
 */

class RealtimeTranscriber {
    constructor() {
        // DOM 元素
        this.apiUrlInput = document.getElementById('apiUrl');
        this.accessTokenInput = document.getElementById('accessToken');
        this.connectBtn = document.getElementById('connectBtn');
        this.disconnectBtn = document.getElementById('disconnectBtn');
        this.startRecordBtn = document.getElementById('startRecordBtn');
        this.stopRecordBtn = document.getElementById('stopRecordBtn');
        this.connStatus = document.getElementById('connStatus');
        this.recordStatus = document.getElementById('recordStatus');
        this.vadStatus = document.getElementById('vadStatus');
        this.transcriptResult = document.getElementById('transcriptResult');
        this.eventLog = document.getElementById('eventLog');
        this.clearLogBtn = document.getElementById('clearLogBtn');

        // 状态
        this.ws = null;
        this.mediaStream = null;
        this.audioContext = null;
        this.isConnected = false;
        this.isRecording = false;
        this.currentSessionId = null;
        this.finalTranscript = '';
        this.interimText = '';

        // 绑定事件
        this.bindEvents();

        // 初始日志
        this.log('系统初始化完成，请输入 Access Token 后点击"连接"', 'event');
    }

    bindEvents() {
        this.connectBtn.addEventListener('click', () => this.connect());
        this.disconnectBtn.addEventListener('click', () => this.disconnect());
        this.startRecordBtn.addEventListener('click', () => this.startRecording());
        this.stopRecordBtn.addEventListener('click', () => this.stopRecording());
        this.clearLogBtn.addEventListener('click', () => this.clearLog());
    }

    connect() {
        const url = this.apiUrlInput.value.trim();
        const token = this.accessTokenInput.value.trim();

        if (!token) {
            this.log('请输入 Access Token', 'error');
            alert('请输入 Access Token');
            return;
        }

        // 构造带 token 的 WebSocket URL
        const wsUrl = `${url}?token=${encodeURIComponent(token)}`;

        this.log(`正在连接: ${url}...`, 'event');

        try {
            this.ws = new WebSocket(wsUrl);

            this.ws.onopen = () => {
                this.isConnected = true;
                this.updateStatus('connStatus', '已连接', 'connected');
                this.updateButtons();
                this.log('WebSocket 连接已建立', 'event');
                this.transcriptResult.innerHTML = '<p class="placeholder">连接成功，点击"开始录音"开始语音转文字...</p>';
            };

            this.ws.onmessage = (event) => {
                this.handleMessage(event.data);
            };

            this.ws.onclose = (event) => {
                this.isConnected = false;
                this.updateStatus('connStatus', '已断开', 'disconnected');
                this.updateButtons();
                this.log(`WebSocket 连接已关闭 (code: ${event.code}, reason: ${event.reason || '无'})`, 'event');
                
                if (this.isRecording) {
                    this.stopRecording();
                }
            };

            this.ws.onerror = (error) => {
                this.log('WebSocket 连接错误', 'error');
                console.error('WebSocket error:', error);
            };

        } catch (error) {
            this.log(`连接失败: ${error.message}`, 'error');
        }
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        if (this.isRecording) {
            this.stopRecording();
        }
    }

    async startRecording() {
        if (!this.isConnected) {
            this.log('请先连接 WebSocket', 'error');
            return;
        }

        try {
            this.mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    channelCount: 1,
                    sampleRate: 16000,
                    echoCancellation: true,
                    noiseSuppression: true
                }
            });

            this.audioContext = new AudioContext({ sampleRate: 16000 });
            const source = this.audioContext.createMediaStreamSource(this.mediaStream);

            // 使用 ScriptProcessorNode 获取原始 PCM 音频数据
            const bufferSize = 4096;
            const processor = this.audioContext.createScriptProcessor(bufferSize, 1, 1);

            processor.onaudioprocess = (e) => {
                if (!this.isRecording) return;

                const inputData = e.inputBuffer.getChannelData(0);
                
                // Float32 → Int16 PCM
                const pcmData = this.float32ToInt16(inputData);
                
                // 发送 PCM 数据
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                    // 将 Int16Array 转为 Blob 发送（WebSocket 支持二进制）
                    const blob = new Blob([pcmData.buffer], { type: 'application/octet-stream' });
                    this.ws.send(blob);
                }
            };

            source.connect(processor);
            processor.connect(this.audioContext.destination);

            // 保存引用以便后续关闭
            this.processor = processor;
            this.source = source;

            this.isRecording = true;
            this.updateStatus('recordStatus', '录音中', 'recording');
            this.updateButtons();
            this.log('开始录音 (16000Hz PCM 单声道)', 'event');

            // 重置转写结果
            this.finalTranscript = '';
            this.interimText = '';
            this.transcriptResult.innerHTML = '<p class="placeholder">正在聆听...</p>';

        } catch (error) {
            this.log(`麦克风访问失败: ${error.message}`, 'error');
            console.error('Microphone access error:', error);
        }
    }

    stopRecording() {
        this.isRecording = false;

        if (this.processor) {
            this.processor.disconnect();
            this.processor = null;
        }
        if (this.source) {
            this.source.disconnect();
            this.source = null;
        }
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(track => track.stop());
            this.mediaStream = null;
        }

        this.updateStatus('recordStatus', '未录音', 'disconnected');
        this.updateButtons();
        this.log('录音已停止', 'event');
    }

    handleMessage(data) {
        try {
            const response = JSON.parse(data);
            const type = response.type;

            if (type === 'result') {
                const transcription = response.transcription;
                if (!transcription) return;

                if (transcription.is_final) {
                    // 最终结果
                    this.finalTranscript += transcription.text;
                    this.interimText = '';
                    this.log(`最终结果: ${transcription.text}`, 'data');
                } else {
                    // 中间结果
                    this.interimText = transcription.text;
                }
                this.updateTranscriptDisplay();

            } else if (type === 'speech_started') {
                this.updateStatus('vadStatus', '检测到语音', 'speaking');
                this.log('VAD: 检测到语音开始', 'event');

            } else if (type === 'speech_stopped') {
                this.updateStatus('vadStatus', '静音', 'disconnected');
                this.log('VAD: 检测到语音停止', 'event');

            } else if (type === 'session.created') {
                this.currentSessionId = response.session?.id;
                this.log(`Session 已创建: ${this.currentSessionId}`, 'event');

            } else {
                this.log(`收到未知事件类型: ${type}`, 'event');
            }
        } catch (e) {
            // 可能是二进制数据（旧版 SDK）
            this.log(`收到非文本数据: ${data?.length || 0} bytes`, 'event');
        }
    }

    updateTranscriptDisplay() {
        let html = '';

        if (this.finalTranscript) {
            html += `<div class="transcript-sentence transcript-final">${this.escapeHtml(this.finalTranscript)}</div>`;
        }
        if (this.interimText) {
            html += `<div class="transcript-sentence transcript-interim">${this.escapeHtml(this.interimText)}</div>`;
        }
        if (!this.finalTranscript && !this.interimText) {
            html = '<p class="placeholder">正在聆听...</p>';
        }

        this.transcriptResult.innerHTML = html;
    }

    float32ToInt16(float32Array) {
        const int16Array = new Int16Array(float32Array.length);
        for (let i = 0; i < float32Array.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Array[i]));
            int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        return int16Array;
    }

    updateStatus(elementId, text, statusClass) {
        const element = document.getElementById(elementId);
        element.textContent = text;
        element.className = `status-badge status-${statusClass}`;
    }

    updateButtons() {
        this.connectBtn.disabled = this.isConnected;
        this.disconnectBtn.disabled = !this.isConnected;
        this.startRecordBtn.disabled = !this.isConnected || this.isRecording;
        this.stopRecordBtn.disabled = !this.isRecording;
    }

    log(message, type = 'event') {
        const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.innerHTML = `<span class="log-time">[${time}]</span><span class="log-${type}">${this.escapeHtml(message)}</span>`;
        this.eventLog.appendChild(entry);
        this.eventLog.scrollTop = this.eventLog.scrollHeight;
    }

    clearLog() {
        this.eventLog.innerHTML = '';
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    window.transcriber = new RealtimeTranscriber();
});
