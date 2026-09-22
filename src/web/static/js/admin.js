// Secure fetch interceptor for Admin API calls
const adminToken = document.querySelector('meta[name="admin-token"]')?.getAttribute("content") || "";
const _originalFetch = window.fetch;
window.fetch = function(url, options = {}) {
    if (typeof url === "string" && url.startsWith("/api/admin") && adminToken) {
        options = options || {};
        options.headers = options.headers || {};
        if (!(options.headers instanceof Headers)) {
            options.headers["X-Admin-Token"] = adminToken;
        }
    }
    return _originalFetch(url, options);
};

let employeesData = [];

document.addEventListener("DOMContentLoaded", () => {
    fetchStatus();
    fetchEmployees();
    fetchCompanyPolicy();

    document.getElementById("btn-sync").addEventListener("click", triggerManualSync);
    document.getElementById("btn-export-backup").addEventListener("click", exportBackup);
    document.getElementById("backup-file-input").addEventListener("change", handleBackupUpload);
    document.getElementById("policy-form").addEventListener("submit", saveCompanyPolicy);
    document.getElementById("search-input").addEventListener("input", filterEmployees);

    initSlackTutorialModal();

    // Auto-refresh every 30 seconds
    setInterval(() => {
        fetchStatus();
        fetchEmployees();
    }, 30000);
});

function showToast(message, isError = false) {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = "toast";
    if (isError) {
        toast.style.borderColor = "#ef4444";
        toast.style.background = "#450a0a";
    }
    toast.innerHTML = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

async function fetchStatus() {
    try {
        const resp = await fetch("/api/admin/metrics");
        if (resp.ok) {
            const data = await resp.json();
            document.getElementById("metric-total-emp").innerText = data.total_employees;
            document.getElementById("metric-active-notifications").innerText = data.active_notifications;
            document.getElementById("metric-synced-today").innerText = data.synced_today;
            document.getElementById("metric-slack-status").innerText = data.slack_connected ? "🟢 Online" : "⚪ Offline";
        }
    } catch (e) {
        console.error("Error fetching metrics:", e);
    }
}

async function fetchEmployees() {
    try {
        const resp = await fetch("/api/admin/employees");
        if (resp.ok) {
            employeesData = await resp.json();
            renderEmployeesTable(employeesData);
        }
    } catch (e) {
        console.error("Error fetching employees:", e);
    }
}

function renderEmployeesTable(list) {
    const tbody = document.getElementById("employees-tbody");
    tbody.innerHTML = "";

    if (!list || list.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 32px;">Nenhum colaborador encontrado.</td></tr>`;
        return;
    }

    list.forEach(emp => {
        const tr = document.createElement("tr");

        const initials = emp.full_name.split(" ").map(n => n[0]).slice(0, 2).join("").toUpperCase();
        const punchesStr = (emp.today_punches && emp.today_punches.length > 0)
            ? emp.today_punches.join("  •  ")
            : "—";

        const stageBadges = {
            "not_started": `<span class="badge badge-muted">⚪ Não iniciado</span>`,
            "first_half": `<span class="badge badge-info">🔵 Manhã</span>`,
            "lunch_break": `<span class="badge badge-warning">🟡 Em Almoço</span>`,
            "second_half": `<span class="badge badge-info">🔵 Tarde</span>`,
            "completed": `<span class="badge badge-success">🟢 Concluído</span>`,
        };
        const stageHtml = stageBadges[emp.current_stage] || `<span class="badge badge-muted">⚪ ${emp.current_stage || "—"}</span>`;

        tr.innerHTML = `
            <td>
                <div class="user-cell">
                    <div class="user-avatar">${initials}</div>
                    <div>
                        <div class="user-name">${emp.full_name}</div>
                        <div class="user-email">${emp.email || "Sem e-mail cadastrado"}</div>
                    </div>
                </div>
            </td>
            <td>
                <label class="switch">
                    <input type="checkbox" ${emp.notifications_enabled ? "checked" : ""} onchange="toggleEmployee('${emp.id}', this.checked)">
                    <span class="slider"></span>
                </label>
            </td>
            <td><code style="background: rgba(0,0,0,0.3); padding: 4px 8px; border-radius: 6px;">${punchesStr}</code></td>
            <td>${stageHtml}</td>
            <td><strong>${emp.worked_hours_str || "00h00m"}</strong></td>
            <td>
                <select class="form-input" style="padding: 4px 8px; width: 110px;" onchange="updateLeadTime('${emp.id}', this.value)">
                    <option value="5" ${emp.lunch_warning_advance_minutes === 5 ? "selected" : ""}>5 min</option>
                    <option value="10" ${emp.lunch_warning_advance_minutes === 10 ? "selected" : ""}>10 min</option>
                    <option value="15" ${emp.lunch_warning_advance_minutes === 15 ? "selected" : ""}>15 min</option>
                </select>
            </td>
            <td>
                <div style="display: flex; gap: 6px;">
                    <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.75rem;" onclick="testEmployeeSlack('${emp.id}')" title="Enviar DM de verificação">
                        💬 Teste
                    </button>
                    <button class="btn btn-secondary" style="padding: 4px 8px; font-size: 0.75rem; background: rgba(99,102,241,0.2); border-color: rgba(99,102,241,0.4);" onclick="simulateWorkday('${emp.id}')" title="Simula batidas faltando 8 min para disparar alerta de fim de expediente">
                        ⏰ Alerta 10m
                    </button>
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function filterEmployees() {
    const q = document.getElementById("search-input").value.toLowerCase();
    const filtered = employeesData.filter(e => 
        e.full_name.toLowerCase().includes(q) || (e.email && e.email.toLowerCase().includes(q))
    );
    renderEmployeesTable(filtered);
}

async function toggleEmployee(employeeId, enabled) {
    try {
        const resp = await fetch(`/api/admin/employees/${employeeId}/toggle`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled })
        });
        if (resp.ok) {
            showToast(`Notificações ${enabled ? "ativadas" : "desativadas"} com sucesso!`);
            fetchStatus();
        } else {
            showToast("Erro ao alterar notificações do colaborador", true);
        }
    } catch (e) {
        showToast("Falha na comunicação com o servidor", true);
    }
}

async function updateLeadTime(employeeId, minutes) {
    try {
        const resp = await fetch(`/api/admin/employees/${employeeId}/preferences`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ advance_minutes: parseInt(minutes) })
        });
        if (resp.ok) {
            showToast(`Tempo de aviso atualizado para ${minutes} minutos!`);
        }
    } catch (e) {
        showToast("Erro ao salvar preferência", true);
    }
}

async function testEmployeeSlack(employeeId) {
    try {
        const resp = await fetch(`/api/admin/employees/${employeeId}/test-slack`, { method: "POST" });
        const res = await resp.json();
        if (res.success) {
            showToast("Mensagem de teste enviada com sucesso no Slack!");
        } else {
            showToast("Falha ao enviar mensagem no Slack: " + (res.detail || "Verifique o token e e-mail"), true);
        }
    } catch (e) {
        showToast("Erro ao disparar teste", true);
    }
}

async function simulateWorkday(employeeId) {
    try {
        const resp = await fetch(`/api/admin/employees/${employeeId}/simulate-workday`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ remaining_minutes: 8 })
        });
        const res = await resp.json();
        if (resp.ok && res.success) {
            showToast(`Simulação ativada! Faltam 8 min para a saída (${res.estimated_end_time}). Alerta disparado no Slack!`);
            await fetchEmployees();
        } else {
            showToast("Falha ao simular jornada: " + (res.detail || "Erro"), true);
        }
    } catch (e) {
        showToast("Erro ao disparar simulação", true);
    }
}

async function resetPunches(employeeId) {
    try {
        const resp = await fetch(`/api/admin/employees/${employeeId}/reset-punches`, { method: "POST" });
        if (resp.ok) {
            showToast("Batidas restauradas para a API oficial do TiqueTaque!");
            await fetchEmployees();
        } else {
            showToast("Erro ao restaurar batidas", true);
        }
    } catch (e) {
        showToast("Falha ao restaurar batidas", true);
    }
}

async function triggerManualSync() {
    const btn = document.getElementById("btn-sync");
    btn.disabled = true;
    btn.innerText = "⏳ Sincronizando...";
    try {
        const resp = await fetch("/api/admin/sync", { method: "POST" });
        if (resp.ok) {
            showToast("Sincronização em lote concluída!");
            await fetchStatus();
            await fetchEmployees();
        } else {
            showToast("Erro durante a sincronização", true);
        }
    } catch (e) {
        showToast("Falha na requisição", true);
    } finally {
        btn.disabled = false;
        btn.innerText = "🔄 Sincronizar Agora";
    }
}

async function fetchCompanyPolicy() {
    try {
        const resp = await fetch("/api/admin/policy");
        if (resp.ok) {
            const data = await resp.json();
            document.getElementById("policy-allow-custom").checked = data.allow_employee_customization;
            const leadTime = data.default_lead_time || data.default_lunch_advance || 10;
            const el = document.getElementById("policy-default-lead-time");
            if (el) el.value = leadTime;
        }
    } catch (e) {
        console.error("Error fetching policy:", e);
    }
}

async function saveCompanyPolicy(e) {
    e.preventDefault();
    const leadTime = parseInt(document.getElementById("policy-default-lead-time").value) || 10;
    const payload = {
        allow_employee_customization: document.getElementById("policy-allow-custom").checked,
        default_lead_time: leadTime,
        default_lunch_advance: leadTime,
        default_end_advance: leadTime,
        default_clt_advance: leadTime,
    };

    try {
        const resp = await fetch("/api/admin/policy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        if (resp.ok) {
            showToast("Diretrizes da empresa salvas com sucesso!");
        } else {
            showToast("Erro ao salvar diretrizes", true);
        }
    } catch (e) {
        showToast("Falha na requisição", true);
    }
}

function exportBackup() {
    window.location.href = "/api/admin/backup/export";
}

async function handleBackupUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (event) => {
        try {
            const json = JSON.parse(event.target.result);
            const resp = await fetch("/api/admin/backup/import", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(json)
            });
            const res = await resp.json();
            if (resp.ok) {
                showToast(`Backup restaurado: ${res.restored_employees_count} colaboradores atualizados!`);
                fetchEmployees();
                fetchCompanyPolicy();
            } else {
                showToast("Arquivo de backup inválido", true);
            }
        } catch (err) {
            showToast("Erro ao processar arquivo JSON", true);
        }
    };
    reader.readAsText(file);
}

function initSlackTutorialModal() {
    const modal = document.getElementById("slack-modal");
    const openBtn = document.getElementById("btn-slack-tutorial");
    const closeBtn = document.getElementById("modal-close-btn");
    const okBtn = document.getElementById("modal-ok-btn");
    const copyBtn = document.getElementById("btn-copy-manifest");
    const manifestCode = document.getElementById("manifest-code");

    if (!modal || !openBtn) return;

    const currentOrigin = window.location.origin.startsWith("http")
        ? window.location.origin
        : "https://seu-dominio.com";

    const manifestObj = {
        "display_information": {
            "name": "TiqueTaque Ponto",
            "description": "Assistente inteligente de jornada e alertas de ponto",
            "background_color": "#1e1b4b"
        },
        "features": {
            "bot_user": {
                "display_name": "TiqueTaque Ponto",
                "always_online": true
            }
        },
        "oauth_config": {
            "scopes": {
                "bot": [
                    "chat:write",
                    "users:read",
                    "users:read.email",
                    "im:write"
                ]
            }
        },
        "settings": {
            "interactivity": {
                "is_enabled": true,
                "request_url": `${currentOrigin}/api/slack/interactions`
            },
            "org_deploy_enabled": false,
            "socket_mode_enabled": false,
            "token_rotation_enabled": false
        }
    };

    const manifestJson = JSON.stringify(manifestObj, null, 2);
    if (manifestCode) {
        manifestCode.innerText = manifestJson;
    }

    openBtn.addEventListener("click", () => {
        modal.classList.add("active");
    });

    const closeModal = () => modal.classList.remove("active");
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    if (okBtn) okBtn.addEventListener("click", closeModal);

    modal.addEventListener("click", (e) => {
        if (e.target === modal) closeModal();
    });

    if (copyBtn) {
        copyBtn.addEventListener("click", async () => {
            try {
                await navigator.clipboard.writeText(manifestJson);
                showToast("📋 Manifesto JSON copiado com sucesso!");
            } catch (err) {
                // Fallback
                const ta = document.createElement("textarea");
                ta.value = manifestJson;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand("copy");
                document.body.removeChild(ta);
                showToast("📋 Manifesto JSON copiado com sucesso!");
            }
        });
    }
}

