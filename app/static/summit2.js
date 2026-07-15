function summit2App() {
  return {
    act: 1,
    cast: [],
    bundles: [],
    fixBundles: [],
    layerInfo: {},
    selectedAttackBundle: null,
    selectedFixBundle: null,
    act3Prompts: ["What are my recent labs?", "Summarize my recent clinical notes.", "What appointments do I have coming up?"],
    callerId: 7,
    sessionId: crypto.randomUUID(),
    chatInput: "",
    chatLog: [],
    toolCallTrace: [],      // accumulates across the whole session, every act — "tracing for all"
    lastSubjectBanner: null,
    recallResult: null,
    lastLatencyMs: null,
    lastCostUsd: null,
    curlUnsigned: "",
    curlSigned: "",
    notesPreview: "",
    classifier: { pending: 0, recent: [], total_classifier_cost_usd: 0, poll_interval_seconds: 5, classifier_model: "" },
    _classifierTimer: null,
    aiguardCatalogue: [],
    aiguardEnabled: false,
    isThinking: false,
    thinkingWord: "",
    _thinkingTimer: null,
    thinkingWords: [
      "Musing", "Percolating", "Philosophising", "Pondering", "Ruminating",
      "Cogitating", "Deliberating", "Noodling", "Contemplating", "Marinating",
      "Excogitating", "Woolgathering",
    ],

    get actTagline() {
      return this.act === 1 ? "Everyone's dangerous mode is literally called Vibe Mode."
           : this.act === 2 ? "Not a magic switch — watch each fix get built, cheapest first."
           : this.act === 3 ? "Same hardened stack. Now watch it get fast and observable."
           : "Architecture answers who. This answers what was actually said.";
    },

    get aiguardStats() {
      const entries = this.toolCallTrace.filter(tc => (tc.tool || "").startsWith("ai_guard"));
      const blocked = entries.filter(tc => tc.blocked).length;
      const allowed = entries.length - blocked;
      const total = entries.length;
      return { allowed, blocked, total, allowedPct: total ? Math.round((allowed / total) * 100) : 0 };
    },

    get lastTrace() {
      return this.toolCallTrace.length ? (this.toolCallTrace[0].trace || []) : [];
    },

    // Act 1 = vibe (leaky, session-only). Act 2 = whatever's active in the fix
    // ladder. Act 3 = the fully hardened stack, always caller-scoped.
    memoryLayers() {
      if (this.act === 3) return ["L7"];
      if (this.act === 2) return this.cumulativeLayers(this.selectedFixBundle);
      return [];
    },
    get memoryLayersLabel() {
      const l = this.memoryLayers();
      return l.length ? l.join("+") + " (caller-scoped)" : "vibe (session-only — the leak)";
    },

    renderMarkdown(text) {
      if (typeof marked !== "undefined" && text) return marked.parse(text);
      return (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br>");
    },

    async init() {
      const [cast, attacks, fixBundles, layers] = await Promise.all([
        fetch("/summit2/api/cast").then(r => r.json()),
        fetch("/summit2/api/attacks").then(r => r.json()),
        fetch("/summit2/api/fix-bundles").then(r => r.json()),
        fetch("/summit2/api/layers").then(r => r.json()),
      ]);
      this.cast = cast.cast;
      this.bundles = attacks.bundles;
      this.fixBundles = fixBundles.bundles;
      this.layerInfo = layers.layers;
      this.selectedAttackBundle = this.bundles[0] || null;
      this.selectedFixBundle = this.fixBundles[0] || null;
      await this.refreshCurl();
      this.refreshClassifier();
      this._classifierTimer = setInterval(() => this.refreshClassifier(), 5000);

      const ag = await fetch("/summit2/api/aiguard-catalogue").then(r => r.json());
      this.aiguardCatalogue = ag.catalogue;
      this.aiguardEnabled = ag.enabled;
    },

    onCallerChange() {
      this.chatLog = [];
      this.lastSubjectBanner = null;
      this.recallResult = null;
      this.refreshCurl();
      this.recallMemory();
    },

    intentColor(intent) {
      const map = {
        "Labs Lookup": "bg-blue-900 text-blue-300",
        "Clinical Notes": "bg-teal-900 text-teal-300",
        "Medication Question": "bg-purple-900 text-purple-300",
        "Appointment": "bg-cyan-900 text-cyan-300",
        "Account / Security": "bg-amber-900 text-amber-300",
        "Personal Info Recall": "bg-pink-900 text-pink-300",
        "Escalation / Safety Concern": "bg-red-900 text-red-300",
        "Other": "bg-slate-700 text-slate-300",
      };
      return map[intent] || map.Other;
    },

    samplePromptsFor(fixBundle) {
      if (!fixBundle) return [];
      const nums = fixBundle.kills;
      const all = this.bundles.flatMap(b => b.attacks);
      return all.filter(a => nums.includes(a.num) && a.prompt).map(a => a.prompt);
    },

    // Cumulative: demo N activates its own layers PLUS every earlier demo's
    // layers, so the audience watches Fortress get built, not swapped.
    cumulativeLayers(fixBundle) {
      if (!fixBundle) return [];
      const idx = this.fixBundles.findIndex(b => b.id === fixBundle.id);
      const upTo = this.fixBundles.slice(0, idx + 1);
      return [...new Set(upTo.flatMap(b => b.layers))];
    },

    // Attack 5 needs two turns + a caller switch to actually show anything —
    // a single quick-prompt button can't demonstrate a leak by itself.
    // Same session_id throughout, chat log deliberately NOT cleared between
    // turns so the whole exchange reads as one continuous, damning thread.
    // Rotates the planted fact each run so it doesn't read as a canned trick.
    async runLeakDemo() {
      const plants = [
        { fact: "My favorite color is teal", question: "What is my favorite color?" },
        { fact: "My dog's name is Biscuit", question: "What is my dog's name?" },
        { fact: "My hometown is Reno, Nevada", question: "What is my hometown?" },
        { fact: "My favorite band is Radiohead", question: "What is my favorite band?" },
      ];
      const plant = plants[Math.floor(Math.random() * plants.length)];
      this.callerId = 7;
      this.chatInput = `${plant.fact}, remember that please.`;
      await this.sendChat();
      this.callerId = 12; // Taylor Morgan — unrelated to Alex, no legitimate reason to know this
      this.chatInput = `What did we just talk about? ${plant.question}`;
      await this.sendChat();
    },

    runQuickPrompt(prompt, callerId, aiGuard = false) {
      if (callerId != null && callerId !== this.callerId) {
        this.callerId = callerId;
        this.onCallerChange();
      }
      this.chatInput = prompt;
      this.sendChat(aiGuard);
    },

    scrollChatToBottom() {
      this.$nextTick(() => {
        if (this.$refs.chatLog) this.$refs.chatLog.scrollTop = this.$refs.chatLog.scrollHeight;
      });
    },

    startThinking() {
      this.isThinking = true;
      const pick = () => this.thinkingWords[Math.floor(Math.random() * this.thinkingWords.length)] + "…";
      this.thinkingWord = pick();
      this._thinkingTimer = setInterval(() => { this.thinkingWord = pick(); }, 900);
      this.scrollChatToBottom();
    },

    stopThinking() {
      this.isThinking = false;
      clearInterval(this._thinkingTimer);
    },

    async sendChat(aiGuard = false) {
      if (!this.chatInput.trim()) return;
      const userText = this.chatInput;
      this.chatLog.push({ id: crypto.randomUUID(), role: "user", text: userText });
      this.chatInput = "";
      this.scrollChatToBottom();
      this.startThinking();

      // Act 1 = raw Vibe baseline, intentionally []. Act 2 = the layers built
      // up so far in the fix ladder. Act 3 ("same hardened stack, now fast +
      // observable") and Act 4 (AI Guard layered ON TOP of a hardened system,
      // not tested against a broken one) both carry the FULL fix stack.
      const fullStack = () => [...new Set(this.fixBundles.flatMap(b => b.layers))];
      const activeLayers = this.act === 2 ? this.cumulativeLayers(this.selectedFixBundle)
        : (this.act === 3 || this.act === 4) ? fullStack()
        : [];
      let data;
      try {
        const resp = await fetch("/summit2/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: this.sessionId,
            caller_id: this.callerId,
            message: userText,
            active_layers: activeLayers,
            ai_guard: aiGuard || this.act === 4,
          }),
        });
        data = await resp.json();
      } finally {
        this.stopThinking();
      }
      const visibilityBadges = (data.tool_calls || []).flatMap(tc => tc.notes_visibility || []);
      this.chatLog.push({
        id: crypto.randomUUID(),
        role: "assistant",
        text: data.text || (data.blocked ? `🚫 ${data.blocked.reason}` : "(no response)"),
        blocked: !!data.blocked,
        visibilityBadges,
      });
      this.scrollChatToBottom();
      this.lastLatencyMs = data.latency_ms;
      this.lastCostUsd = data.cost_usd;
      this.recordTrace(data.tool_calls || []);
      this.updateSubjectBanner(data.tool_calls || []);
      this.recallMemory();
    },

    // Accumulating trace across every act, not overwritten per turn — this
    // was the "no tracing is bad" gap: only the latest call was ever visible.
    recordTrace(toolCalls) {
      const tagged = toolCalls.map(tc => ({
        ...tc, act: this.act, expanded: false, ts: new Date().toLocaleTimeString(),
      }));
      this.toolCallTrace = [...tagged.reverse(), ...this.toolCallTrace].slice(0, 40);
    },

    // Mirrors DEFCON's own audit-card pattern (app.js _applyAuditStyling) —
    // three visually distinct outcomes, same spirit as DEFCON's four (no
    // "guardrails-only" state here): accent = engine intervened, safe =
    // legitimately allowed, pop = a raw leak.
    badgeFor(tc) {
      const isAiGuard = (tc.tool || "").startsWith("ai_guard");
      if (tc.blocked) {
        return { label: isAiGuard ? "BLOCKED" : "ENGINE BLOCKED", icon: "block", border: "border-accent", text: "text-accent", bg: "bg-accent/25 text-accent" };
      }
      if (isAiGuard) {
        return { label: "ALLOWED", icon: "check_circle", border: "border-safe", text: "text-safe", bg: "bg-safe/25 text-safe" };
      }
      // Own-record access is never a leak, layers or no layers — "get_my_labs"
      // returning your own labs isn't a violation just because Vibe mode has
      // no guardrails active. Only flag LEAKED when it's someone else's record.
      if (tc.subject && tc.subject.is_caller) {
        return { label: "ALLOWED", icon: "check_circle", border: "border-safe", text: "text-safe", bg: "bg-safe/25 text-safe" };
      }
      const anyPass = (tc.trace || []).some(s => s.outcome === "pass");
      if (anyPass) {
        return { label: "ALLOWED", icon: "check_circle", border: "border-safe", text: "text-safe", bg: "bg-safe/25 text-safe" };
      }
      if (tc.subject && tc.subject.is_caller === false) {
        return { label: "LEAKED", icon: "error", border: "border-pop", text: "text-pop", bg: "bg-danger/30 text-pop" };
      }
      // No subject at all (e.g. admin_list_all_patients, query_database) —
      // not tied to one patient's record, but still unguarded in Vibe mode.
      return { label: "UNGUARDED", icon: "error", border: "border-pop", text: "text-pop", bg: "bg-danger/30 text-pop" };
    },

    decisionText(tc) {
      if (tc.blocked) return tc.reason;
      if ((tc.tool || "").startsWith("ai_guard")) return "Trend Vision One: no policy violation detected";
      const passed = (tc.trace || []).filter(s => s.outcome === "pass").map(s => s.layer);
      return passed.length ? `passed: ${passed.join(", ")}` : "no active guardrail for this tool";
    },

    // The single biggest demo-clarity fix: name whose record just got touched,
    // in big bold text, not buried in a JSON blob.
    updateSubjectBanner(toolCalls) {
      const withSubject = toolCalls.find(tc => tc.subject && !tc.blocked);
      if (!withSubject) {
        this.lastSubjectBanner = null;
        return;
      }
      const s = withSubject.subject;
      if (s.is_caller) {
        this.lastSubjectBanner = { crossPatient: false, text: `📁 Data shown: ${s.name}'s own record (P${s.id})` };
      } else {
        this.lastSubjectBanner = { crossPatient: true, text: `🚨 Data shown: ${s.name}'s record (P${s.id}) — NOT the caller's own` };
      }
    },

    async recallMemory() {
      const layers = this.memoryLayers().join(",");
      const resp = await fetch(`/summit2/api/recall?session_id=${this.sessionId}&caller_id=${this.callerId}&layers=${layers}`);
      this.recallResult = await resp.json();
    },

    async showNotesPreview() {
      const layers = this.cumulativeLayers(this.selectedFixBundle).join(",");
      const resp = await fetch(`/summit2/api/notes-preview?caller_id=${this.callerId}&layers=${layers}`).then(r => r.json());
      this.notesPreview = JSON.stringify(resp.notes_as_seen_by_model, null, 2);
    },

    async refreshCurl() {
      const mcpSessionId = "summit2-mcp-demo";
      const sig = await fetch(`/summit2/api/sign?session_id=${mcpSessionId}&caller_id=${this.callerId}`).then(r => r.json());
      const url = `/summit2/mcp/get_patient_labs?require_sig=true&session_id=${mcpSessionId}`;
      this.curlUnsigned =
        `curl -X POST '${url}' \\\n  -d '{"patient_id": 12}'\n→ 401 Missing X-Caller-Sig header`;
      this.curlSigned =
        `curl -X POST '${url}' \\\n  -H "X-Caller-Sig: ${sig.token}" \\\n  -d '{"patient_id": 12}'\n→ 200 (or 403 if caller isn't authorized for patient 12)`;
    },

    async refreshClassifier() {
      this.classifier = await fetch("/summit2/api/classifier").then(r => r.json());
    },
  };
}
