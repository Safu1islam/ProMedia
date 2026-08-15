<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, ApiError } from "../api";

const router = useRouter();
const loading = ref(true);
const error = ref<string | null>(null);
const tab = ref<"Accounts" | "Queue" | "Publications" | "Composer" | "Insights">("Accounts");

const accounts = ref<any[]>([]);
const posts = ref<any[]>([]);
const publications = ref<any[]>([]);

const platform = ref("x");
const handle = ref("");
const secret = ref("");
const connecting = ref(false);
const connectError = ref<string | null>(null);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [acc, postList, pubs] = await Promise.all([api.listAccounts(), api.listPosts(), api.publications()]);
    accounts.value = acc.accounts;
    posts.value = postList.posts;
    publications.value = pubs.publications;
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : "could not reach the server";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

async function connect() {
  if (!handle.value.trim()) return;
  connecting.value = true;
  connectError.value = null;
  try {
    await api.connectAccount(platform.value, handle.value.trim(), secret.value || undefined);
    handle.value = "";
    secret.value = "";
    await load();
  } catch (err) {
    connectError.value = err instanceof ApiError ? err.message : "could not connect";
  } finally {
    connecting.value = false;
  }
}
</script>

<template>
  <section class="social">
    <div class="head">
      <div>
        <h1>Social integration</h1>
        <p class="muted">Accounts, the publish queue, and what actually went out.</p>
      </div>
      <div class="tabs">
        <button v-for="t in ['Accounts', 'Queue', 'Publications', 'Composer', 'Insights']" :key="t"
                :class="{ active: tab === t }" @click="tab = t as any">{{ t }}</button>
      </div>
    </div>

    <div v-if="loading" class="state muted">Loading…</div>
    <div v-else-if="error" class="state banner bad">{{ error }}</div>
    <div v-else class="body">
      <template v-if="tab === 'Accounts'">
        <div class="cards">
          <div v-for="a in accounts" :key="a.id" class="card">
            <div class="card-head">
              <strong>{{ a.platform }}</strong>
              <span class="pill" :class="`tone-${a.status === 'connected' ? 'green' : 'red'}`">{{ a.status }}</span>
            </div>
            <div class="muted mono small">{{ a.handle }}</div>
            <div class="muted mono small">{{ a.credential_ref }}</div>
          </div>
          <div v-if="!accounts.length" class="muted">No accounts connected.</div>
        </div>
        <form class="connect" @submit.prevent="connect">
          <select v-model="platform"><option value="x">x</option><option value="linkedin">linkedin</option></select>
          <input v-model="handle" type="text" placeholder="handle" required />
          <input v-model="secret" type="password" placeholder="credential (optional to reconnect)" autocomplete="new-password" />
          <button class="btn primary" type="submit" :disabled="connecting">Connect</button>
        </form>
        <div v-if="connectError" class="banner bad">{{ connectError }}</div>
      </template>

      <template v-else-if="tab === 'Queue'">
        <table>
          <thead><tr><th>Post</th><th>Status</th><th>Body</th></tr></thead>
          <tbody>
            <tr v-for="p in posts" :key="p.id" class="row" tabindex="0"
                :aria-label="`Open post ${p.id}`"
                @click="router.push(`/posts/${p.id}`)"
                @keydown.enter="router.push(`/posts/${p.id}`)"
                @keydown.space.prevent="router.push(`/posts/${p.id}`)">
              <td class="mono">{{ p.id }}</td>
              <td>{{ p.status }}</td>
              <td class="truncate">{{ p.body.slice(0, 80) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!posts.length" class="muted">Nothing queued.</div>
      </template>

      <template v-else-if="tab === 'Publications'">
        <table>
          <thead><tr><th>Post</th><th>Platform post id</th><th>Published</th><th></th></tr></thead>
          <tbody>
            <tr v-for="pub in publications" :key="pub.id">
              <td class="mono"><router-link :to="`/posts/${pub.post_id}`">{{ pub.post_id }}</router-link></td>
              <td class="mono">{{ pub.platform_post_id }}</td>
              <td class="mono">{{ pub.published_at.slice(0, 16).replace("T", " ") }}</td>
              <td><span v-if="pub.simulated" class="pill tone-red">SIMULATED — never published</span></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!publications.length" class="muted">Nothing published yet.</div>
      </template>

      <template v-else>
        <div class="card">
          <div class="card-head"><strong>Not available in this client yet</strong> <span class="pill tone-amber">T-059</span></div>
          <p class="muted">
            Cross-platform variant preparation and analytics beyond what informs scheduling
            (project.md section 3, S6) are not built. Nothing here is fabricated to fill the gap.
          </p>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.social {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 20px 28px 0;
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
.tabs {
  display: flex;
  gap: 2px;
}
.tabs button {
  all: unset;
  cursor: pointer;
  padding: 8px 13px;
  font: 500 12.5px var(--font-ui);
  color: var(--fg-muted-2);
  border-bottom: 2px solid transparent;
}
.tabs button.active {
  color: var(--fg-bright);
  border-bottom-color: var(--green);
}
.body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 0 32px;
}
.state {
  padding: 30px 0;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.card {
  border-radius: var(--radius-lg);
  background: var(--bg-panel);
  border: 1px solid var(--line-3);
  padding: 12px 14px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.small {
  font-size: 11px;
}
.connect {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.connect input,
.connect select {
  font: inherit;
  padding: 0.45rem 0.55rem;
  border: 1px solid var(--line-5);
  border-radius: 6px;
  background: var(--bg-field);
  color: inherit;
}
.btn {
  all: unset;
  cursor: pointer;
  padding: 0.5rem 1rem;
  border-radius: 7px;
  font: 600 12px var(--font-ui);
}
.btn.primary {
  background: var(--green);
  color: var(--green-ink);
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
tr.row {
  cursor: pointer;
}
tr.row:hover td {
  background: var(--bg-card);
}
tr.row:focus-visible {
  outline: var(--focus-ring);
  outline-offset: -2px;
}
.truncate {
  max-width: 40ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.banner.bad {
  border-left: 4px solid var(--red);
  background: var(--bg-panel);
  padding: 0.7rem 0.9rem;
  border-radius: 0 6px 6px 0;
  margin-top: 10px;
}
</style>
