// Summit demo — Alpine component
function summitApp() {
  return {
    identity: {
      tenant_id: "lab-default",
      user_id: "7",
      session_id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
    },
    patientChat: [],
    clinicianChat: [],
    patientInput: "",
    clinicianInput: "",
    lastInspector: null,
    recentLog: [],
    routing: [],
    sessionCost: 0,
    guardrailStatus: "…checking",
    // PP-03b mode toggles
    patientMode: "chatbot_session", // chatbot_session | agentic | streaming
    clinicianMode: "agentic",       // agentic | batch | streaming
    // PP-03a session memory panel
    sessionInfo: { state: "cold", turns: 0, age_sec: 0 },
    // PP-03c swarm panel
    swarmResult: null,
    swarmRunning: false,
    // PP-03d tool auto-discovery panel
    toolCatalog: [],

    // Sample prompts — click-to-send on stage
    patientSamples: [
      "give me my labs",
      "what are my notes?",
      "what are three tips for sleeping better?",
      "hi, my favourite number is 42. remember it.",
      "what is my favourite number?",
    ],
    clinicianSamples: [
      "summarise Patient 12's recent labs",
      "list flagged patients across the clinic",
      "pull the full chart for patient 7",
      "what should I watch for overnight on patient 12?",
    ],

    usePatientSample(text) {
      this.patientInput = text;
      this.sendPatient();
    },

    useClinicianSample(text) {
      this.clinicianInput = text;
      this.sendClinician();
    },

    async init() {
      this.loadRouting();
      this.loadGuardrailStatus();
      this.loadTools();
      this.refreshSession();
    },

    async loadRouting() {
      try {
        const r = await fetch("/summit/api/routing");
        if (r.ok) this.routing = await r.json();
      } catch (e) {
        // SM0 stub — endpoint doesn't exist yet
      }
    },

    async loadGuardrailStatus() {
      try {
        const r = await fetch("/summit/api/guardrail");
        if (r.ok) {
          const data = await r.json();
          this.guardrailStatus = data.id_set ? "✅ configured" : "⚠️ not set";
        }
      } catch (e) {
        this.guardrailStatus = "—";
      }
    },

    async loadTools() {
      try {
        const r = await fetch("/summit/api/tools");
        if (r.ok) this.toolCatalog = await r.json();
      } catch (e) {
        this.toolCatalog = [];
      }
    },

    async refreshSession() {
      try {
        const r = await fetch("/summit/api/session", {
          headers: { "X-Session-Id": this.identity.session_id },
        });
        if (r.ok) this.sessionInfo = await r.json();
      } catch (e) {}
    },

    async resetSession() {
      try {
        await fetch("/v1/session/reset", {
          method: "POST",
          headers: { "X-Session-Id": this.identity.session_id },
        });
        this.patientChat = [];
        this.refreshSession();
      } catch (e) {}
    },

    shortModel(modelId) {
      if (!modelId) return "";
      if (modelId.includes("haiku")) return "Haiku 4.5";
      if (modelId.includes("sonnet")) return "Sonnet 4.5";
      if (modelId.includes("nova-lite")) return "Nova Lite";
      return modelId;
    },

    async sendPatient() {
      const text = this.patientInput.trim();
      if (!text) return;
      this.patientInput = "";
      this.patientChat.push({ id: Date.now() + "u", role: "user", text });
      const botId = Date.now() + "b";
      this.patientChat.push({ id: botId, role: "bot", text: "…" });
      if (this.patientMode === "streaming") {
        await this._inferStream("patient_chat", text, this.patientChat, botId);
      } else {
        await this._infer("patient_chat", text, this.patientChat, botId, this.patientMode);
      }
    },

    async sendClinician() {
      const text = this.clinicianInput.trim();
      if (!text) return;
      this.clinicianInput = "";
      this.clinicianChat.push({ id: Date.now() + "u", role: "user", text });
      const botId = Date.now() + "b";
      this.clinicianChat.push({ id: botId, role: "bot", text: "…" });
      if (this.clinicianMode === "streaming") {
        await this._inferStream("clinician_summary", text, this.clinicianChat, botId);
      } else {
        await this._infer("clinician_summary", text, this.clinicianChat, botId, this.clinicianMode);
      }
    },

    async runSwarm() {
      this.swarmRunning = true;
      this.swarmResult = null;
      try {
        const r = await fetch("/v1/swarm", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Tenant-Id": this.identity.tenant_id,
            "X-User-Id": this.identity.user_id,
            "X-Session-Id": this.identity.session_id,
          },
          body: JSON.stringify({
            product_id: "clinician_summary",
            user_message: "Patient 12: apoB 120, hsCRP 8. Summarise overnight priorities.",
            skill_ids: ["biomarker-analysis", "inflammation-analysis", "clinical-safety"],
          }),
        });
        this.swarmResult = await r.json();
        if (this.swarmResult.totals) {
          this.sessionCost += this.swarmResult.totals.cost_usd || 0;
        }
      } catch (e) {
        this.swarmResult = { error: String(e) };
      } finally {
        this.swarmRunning = false;
      }
    },

    async _infer(product_id, user_message, chatArray, botId, mode) {
      try {
        const r = await fetch("/v1/infer", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Tenant-Id": this.identity.tenant_id,
            "X-User-Id": this.identity.user_id,
            "X-Session-Id": this.identity.session_id,
          },
          body: JSON.stringify({ product_id, user_message, skill_ids: null, mode: mode || "agentic" }),
        });
        const data = await r.json();
        const bot = chatArray.find((m) => m.id === botId);
        if (bot) {
          if (data.stub) {
            bot.text = "[SM0 stub] orchestrator not wired yet. Headers: " + JSON.stringify(data.headers);
          } else if (data.text) {
            bot.text = data.text;
          } else if (data.error) {
            bot.text = "Error: " + data.error;
          } else {
            bot.text = JSON.stringify(data);
          }
        }
        if (data.inspector) {
          this.lastInspector = data.inspector;
          this.sessionCost += data.inspector.cost_usd || 0;
          this.recentLog.unshift(data.inspector);
          if (this.recentLog.length > 20) this.recentLog.pop();
          if (data.inspector.session) this.sessionInfo = data.inspector.session;
        }
        this.refreshSession();
      } catch (e) {
        const bot = chatArray.find((m) => m.id === botId);
        if (bot) bot.text = "Network error: " + e.message;
      }
    },

    async _inferStream(product_id, user_message, chatArray, botId) {
      try {
        const r = await fetch("/v1/infer/stream", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Tenant-Id": this.identity.tenant_id,
            "X-User-Id": this.identity.user_id,
            "X-Session-Id": this.identity.session_id,
          },
          body: JSON.stringify({ product_id, user_message, skill_ids: null, mode: "streaming" }),
        });
        if (!r.body) {
          const bot = chatArray.find((m) => m.id === botId);
          if (bot) bot.text = "(streaming unsupported in this browser)";
          return;
        }
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        const bot = chatArray.find((m) => m.id === botId);
        if (bot) bot.text = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop();
          for (const part of parts) {
            if (!part.startsWith("data: ")) continue;
            let event;
            try { event = JSON.parse(part.slice(6)); } catch { continue; }
            if (event.type === "chunk" && bot) {
              bot.text += event.text;
            } else if (event.type === "done" && event.inspector) {
              this.lastInspector = event.inspector;
              this.sessionCost += event.inspector.cost_usd || 0;
              this.recentLog.unshift(event.inspector);
              if (this.recentLog.length > 20) this.recentLog.pop();
            }
          }
        }
      } catch (e) {
        const bot = chatArray.find((m) => m.id === botId);
        if (bot) bot.text = "Stream error: " + e.message;
      }
    },
  };
}
