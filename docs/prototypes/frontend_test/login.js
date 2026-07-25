/**
 * 登录/注册页面逻辑
 * 调用后端 /api/v1/auth/login 和 /api/v1/auth/register
 * 登录成功后将 token 存入 localStorage，跳转 meeting.html
 */

// 后端 API 基础地址
// 页面通过后端 /test 挂载访问时（HTTP 协议，无论 localhost 还是局域网 IP），用相对路径同源访问
// 仅 file:// 直接打开时回退到 localhost
const API_BASE = location.protocol.startsWith('http')
    ? ''                       // 同源：相对路径，浏览器自动用当前 origin（localhost 或局域网 IP）
    : 'http://localhost:31818'; // file:// 回退

const loginForm = document.getElementById('loginForm');
const registerForm = document.getElementById('registerForm');
const errorMsg = document.getElementById('errorMsg');
const successMsg = document.getElementById('successMsg');

// 切换登录/注册
document.getElementById('toRegister').addEventListener('click', () => {
    loginForm.classList.remove('active');
    registerForm.classList.add('active');
    hideMessages();
});

document.getElementById('toLogin').addEventListener('click', () => {
    registerForm.classList.remove('active');
    loginForm.classList.add('active');
    hideMessages();
});

function showError(msg) {
    errorMsg.textContent = msg;
    errorMsg.classList.add('show');
    successMsg.classList.remove('show');
}

function showSuccess(msg) {
    successMsg.textContent = msg;
    successMsg.classList.add('show');
    errorMsg.classList.remove('show');
}

function hideMessages() {
    errorMsg.classList.remove('show');
    successMsg.classList.remove('show');
}

// 登录
document.getElementById('loginBtn').addEventListener('click', async () => {
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value.trim();

    if (!username || !password) {
        showError('用户名和密码不能为空');
        return;
    }

    hideMessages();
    const btn = document.getElementById('loginBtn');
    btn.disabled = true;
    btn.textContent = '登录中...';

    try {
        const resp = await fetch(`${API_BASE}/api/v1/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });

        const data = await resp.json();

        if (resp.ok && data.status_code === 200) {
            // 存储 token
            localStorage.setItem('access_token', data.data.access_token);
            localStorage.setItem('refresh_token', data.data.refresh_token);
            localStorage.setItem('username', username);
            showSuccess('登录成功，正在跳转...');
            setTimeout(() => {
                location.href = 'meeting.html';
            }, 500);
        } else {
            showError(data.detail || data.status_message || '登录失败');
            btn.disabled = false;
            btn.textContent = '登录';
        }
    } catch (e) {
        showError(`网络错误: ${e.message}`);
        btn.disabled = false;
        btn.textContent = '登录';
    }
});

// 注册
document.getElementById('registerBtn').addEventListener('click', async () => {
    const username = document.getElementById('regUsername').value.trim();
    const password = document.getElementById('regPassword').value.trim();
    const confirm = document.getElementById('regConfirm').value.trim();

    if (!username || !password || !confirm) {
        showError('请填写所有字段');
        return;
    }
    if (password !== confirm) {
        showError('两次密码不一致');
        return;
    }

    hideMessages();
    const btn = document.getElementById('registerBtn');
    btn.disabled = true;
    btn.textContent = '注册中...';

    try {
        const resp = await fetch(`${API_BASE}/api/v1/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, confirmPassword: confirm }),
        });

        const data = await resp.json();

        if (resp.ok && data.status_code === 200) {
            showSuccess('注册成功，请登录');
            registerForm.classList.remove('active');
            loginForm.classList.add('active');
            document.getElementById('loginUsername').value = username;
            btn.disabled = false;
            btn.textContent = '注册';
        } else {
            showError(data.detail || data.status_message || '注册失败');
            btn.disabled = false;
            btn.textContent = '注册';
        }
    } catch (e) {
        showError(`网络错误: ${e.message}`);
        btn.disabled = false;
        btn.textContent = '注册';
    }
});

// 回车提交
document.getElementById('loginPassword').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') document.getElementById('loginBtn').click();
});
document.getElementById('regConfirm').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') document.getElementById('registerBtn').click();
});
