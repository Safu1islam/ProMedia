<script setup lang="ts">
// Capability directory (T-071, DR-023). Deliberately NOT called "marketplace"
// anywhere in this file, including comments read by a future editor: DR-023
// scoped this screen honestly as a projection of T-048's existing provider
// registry (list-capabilities, capability-requirements, estimate-capability-
// cost, run-capability, spend-status, spend-history) — a literal live
// multi-vendor marketplace with browsing/purchasing was ruled out as
// violating T-048's own "no purchasing or payment code" rule, C-31, and O-3
// (no pricing from memory). No new backend operation exists for this screen.
//
// AC-3 (grepped as part of this task's own evidence, not assumed): this file
// contains no control of the kind an e-commerce or billing flow would need —
// nothing that acquires, pays for, or enrols in anything. "Try it" runs the
// real run-capability operation, which structurally refuses today
// (core/providers/base.py) and shows exactly why — it is not an acquisition
// control.
import { computed, onMounted, ref } from "vue";
import { api, ApiError } from "../api";

interface Requirement {
  kind: string;
  name: string;
  detail: string;
}
interface Requirements {
  capability: string;
  provider: string;
  satisfied: boolean;
  missing: Requirement[];
  note: string;
}
interface CapabilityRow {
  capability: string;
  provider: string;
  available: boolean;
  requirements: Requirements;
}
interface Estimate {
  unit: string;
  unit_cost_usd: number | string;
  basis: string;
  note: string;
}

const loading = ref(true);
const error = ref<string | null>(null);
const capabilities = ref<CapabilityRow[]>([]);
const estimates = ref<Record<string, Estimate>>({});
const spendStatus = ref<any>(null);
const spendHistory = ref<any[]>([]);

// Per-card "try it" state, keyed by capability kind — run-capability is a
// real operator-authority call (core/ops/providers.py), never simulated. Its
// structural refusal is the honest answer, shown verbatim.
const trying = ref<Record<string, boolean>>({});
const tryResult = ref<Record<string, { ok: boolean; message: string } | null>>({});

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [caps, status, history] = await Promise.all([
      api.listCapabilities(),
      api.spendStatus(),
      api.spendHistory(),
    ]);
    capabilities.value = caps.capabilities;
    spendStatus.value = status;
    spendHistory.value = history.entries;

    const pairs = await Promise.all(
      capabilities.value.map(async (c) => {
        const est = await api.estimateCapabilityCost(c.capability);
        return [c.capability, est] as const;
      }),
    );
    estimates.value = Object.fromEntries(pairs);
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : "could not reach the server";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

async function tryCapability(kind: string) {
  trying.value = { ...trying.value, [kind]: true };
  tryResult.value = { ...tryResult.value, [kind]: null };
  try {
    await api.runCapability(kind);
    // Unreachable today by construction (core/providers/base.py) — every
    // capability refuses before this line. Handled anyway so a future live
    // adapter does not silently show nothing on success.
    tryResult.value = { ...tryResult.value, [kind]: { ok: true, message: "ran successfully" } };
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "could not reach the server";
    tryResult.value = { ...tryResult.value, [kind]: { ok: false, message } };
  } finally {
    trying.value = { ...trying.value, [kind]: false };
  }
}

function requirementTone(kind: string): string {
  if (kind === "package") return "amber";
  if (kind === "api_credential") return "amber";
  return "grey"; // verified_pricing — always missing today, see base.py
}

const CAPABILITY_LABELS: Record<string, string> = {
  transcription: "Transcription",
  text: "Text",
  speech: "Speech",
  image: "Image",
  video: "Video",
};

function spendTone(state: string): string {
  if (state === "hard_stopped") return "red";
  if (state === "over_ceiling") return "amber";
  return "green";
}

const spendPct = computed(() => {
  if (!spendStatus.value) return 0;
  const { committed_usd, hard_stop_usd } = spendStatus.value;
  if (!hard_stop_usd) return 0;
  return Math.min(100, Math.round((committed_usd / hard_stop_usd) * 100));
});
</script>

<template>
  <section class="capdir">
    <div class="head">
      <div>
        <h1>Capability directory</h1>
        <p class="muted">
          What each AI capability can do on this machine today, exactly what would make it
          available, and the C-31 spend ledger. This is a directory, not a store — nothing here
          can be bought or signed up for; acquiring a real provider still means an operator
          installing a package and setting a credential by hand.
        </p>
      </div>
    </div>

    <div v-if="loading" class="state muted">Loading…</div>
    <div v-else-if="error" class="state banner bad">{{ error }}</div>
    <template v-else>
      <div class="cards">
        <div v-for="c in capabilities" :key="c.capability" class="card">
          <div class="card-head">
            <span class="card-title">{{ CAPABILITY_LABELS[c.capability] ?? c.capability }}</span>
            <span class="pill" :class="c.available ? 'tone-green' : 'tone-amber'">
              {{ c.available ? "available" : "unavailable" }}
            </span>
          </div>
          <div class="card-body">
            <p class="provider muted small">{{ c.requirements.provider }}</p>

            <div class="section">
              <h3>Missing</h3>
              <ul v-if="c.requirements.missing.length" class="missing-list">
                <li v-for="m in c.requirements.missing" :key="m.name">
                  <span class="pill" :class="`tone-${requirementTone(m.kind)}`">{{ m.kind.replaceAll("_", " ") }}</span>
                  <span class="missing-name mono">{{ m.name }}</span>
                  <span class="missing-detail muted small">{{ m.detail }}</span>
                </li>
              </ul>
              <p v-else class="muted small">Nothing missing.</p>
            </div>

            <div class="section">
              <h3>Estimated cost</h3>
              <p class="mono small cost">
                {{ estimates[c.capability]?.unit_cost_usd ?? "…" }}
              </p>
              <p class="muted small">{{ estimates[c.capability]?.note }}</p>
            </div>

            <div class="section">
              <h3>Run</h3>
              <button
                class="btn"
                type="button"
                :disabled="trying[c.capability]"
                @click="tryCapability(c.capability)"
              >
                {{ trying[c.capability] ? "Running…" : "Try it" }}
              </button>
              <p v-if="tryResult[c.capability]" class="try-result muted small"
                 :class="{ bad: !tryResult[c.capability]?.ok }">
                {{ tryResult[c.capability]?.message }}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div class="ledger" v-if="spendStatus">
        <h2>Spend ledger</h2>
        <p class="muted small">C-31: $100/month ceiling, hard stop at $150. Every entry below is a record of a
          spend that already happened elsewhere — nothing on this screen can create one.</p>
        <div class="ledger-summary">
          <div class="stat">
            <span class="stat-label">Committed this month</span>
            <span class="stat-value mono">${{ spendStatus.committed_usd.toFixed(2) }}</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill" :class="`tone-${spendTone(spendStatus.state)}`" :style="{ width: `${spendPct}%` }"></div>
          </div>
          <div class="stat-row">
            <span class="muted small">Ceiling ${{ spendStatus.monthly_ceiling_usd.toFixed(2) }}</span>
            <span class="muted small">Hard stop ${{ spendStatus.hard_stop_usd.toFixed(2) }}</span>
            <span class="pill" :class="`tone-${spendTone(spendStatus.state)}`">{{ spendStatus.state.replaceAll("_", " ") }}</span>
          </div>
        </div>

        <table v-if="spendHistory.length">
          <thead><tr><th>When</th><th>Capability</th><th>Provider</th><th>Amount</th><th>Note</th></tr></thead>
          <tbody>
            <tr v-for="e in spendHistory" :key="e.id">
              <td class="mono">{{ e.recorded_at.slice(0, 16).replace("T", " ") }}</td>
              <td>{{ e.capability }}</td>
              <td>{{ e.provider }}</td>
              <td class="mono">${{ Number(e.amount_usd).toFixed(2) }}</td>
              <td class="muted small">{{ e.note || "—" }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted small">No spend recorded yet.</p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.capdir {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 20px 28px 36px;
  overflow-y: auto;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}
h1 {
  margin: 0;
  font: 600 20px var(--font-ui);
}
p.muted {
  max-width: 68ch;
  color: var(--fg-muted-2);
}
.state {
  padding: 30px 0;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
  margin: 16px 0 24px;
}
.card {
  border-radius: var(--radius-xl);
  background: var(--bg-panel);
  border: 1px solid var(--line-3);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.card-head {
  padding: 12px 16px;
  border-bottom: 1px solid var(--line-3);
  display: flex;
  align-items: center;
  gap: 9px;
}
.card-title {
  font: 600 13px var(--font-ui);
  flex: 1;
}
.card-body {
  padding: 12px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.provider {
  margin: -4px 0 0;
}
.section h3 {
  margin: 0 0 6px;
  font: 600 10.5px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--fg-muted-3);
}
.missing-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.missing-list li {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  flex-wrap: wrap;
}
.missing-name {
  font-size: 11px;
  color: var(--fg-dim);
}
.missing-detail {
  flex-basis: 100%;
  line-height: 1.4;
}
.cost {
  color: var(--fg-dim);
}
.small {
  font-size: 11px;
}
.btn {
  all: unset;
  cursor: pointer;
  padding: 6px 12px;
  border-radius: 7px;
  background: var(--bg-chip);
  border: 1px solid var(--line-5);
  color: var(--fg-dim);
  font: 600 11.5px var(--font-ui);
}
.btn:hover {
  background: var(--bg-card);
}
.btn:disabled {
  opacity: 0.6;
  cursor: default;
}
.btn:focus-visible {
  outline: var(--focus-ring);
  outline-offset: 2px;
}
.try-result {
  margin: 8px 0 0;
  line-height: 1.4;
}
.try-result.bad {
  color: var(--red-soft, var(--red));
}
.ledger {
  border-top: 1px solid var(--line-3);
  padding-top: 18px;
}
.ledger h2 {
  margin: 0 0 4px;
  font: 600 15px var(--font-ui);
}
.ledger-summary {
  margin: 12px 0 18px;
  max-width: 52ch;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 6px;
}
.stat-label {
  font-size: 11px;
  color: var(--fg-muted-3);
}
.stat-value {
  font-size: 18px;
  font-weight: 600;
}
.bar-track {
  height: 8px;
  border-radius: 4px;
  background: var(--bg-chip);
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 4px;
}
.bar-fill.tone-green {
  background: var(--green);
}
.bar-fill.tone-amber {
  background: var(--amber);
}
.bar-fill.tone-red {
  background: var(--red);
}
.stat-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
  flex-wrap: wrap;
}
table {
  border-collapse: collapse;
  width: 100%;
}
th,
td {
  text-align: left;
  padding: 0.5rem 0.6rem;
  border-bottom: 1px solid var(--line-2);
  font-size: 12.5px;
}
th {
  font: 500 10px var(--font-mono);
  color: var(--fg-muted-3);
}
.banner {
  border-left: 4px solid var(--amber);
  background: var(--bg-panel);
  padding: 0.7rem 0.9rem;
  border-radius: 0 6px 6px 0;
}
.banner.bad {
  border-left-color: var(--red);
}
.pill {
  flex: none;
}
.tone-grey {
  background: var(--grey-wash);
  color: var(--grey-fg);
}
.tone-green {
  background: var(--green-wash);
  color: var(--green);
}
.tone-amber {
  background: var(--amber-wash);
  color: var(--amber);
}
.tone-red {
  background: var(--red-wash);
  color: var(--red-soft);
}
.tone-blue {
  background: var(--blue-wash);
  color: var(--blue);
}
</style>
