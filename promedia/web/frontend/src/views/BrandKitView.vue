<script setup lang="ts">
// Brand kits (T-069, DR-021). A brand kit is data ABOUT how to build an EDL —
// name, logo, two colours, a font — never a second thing a render reads.
// Applying one calls apply-brand-kit, which burns the logo into a NEW EDL
// version through the existing set-edl; this screen never talks to edl.py or
// render.py directly, and never re-reads a kit after applying it.
//
// AC-1: the logo goes through the exact same rights-declaration-at-import
// path every other asset uses (frontend-brief.md's binding rule — no path
// may acquire media without a declaration). This screen does not invent a
// second upload route: uploadLogo() below posts to the SAME /media route
// MediaView.vue uses (T-050), and create-brand-kit's own server-side gate
// (_require_rights_declared) refuses a logo with no declaration regardless
// of what this form does — the client-side disabled-until-declared button is
// a courtesy, not the enforcement.
//
// AC-2: applying a kit's new EDL version shows up, correctly attributed,
// in the target project's version history — with ZERO changes to
// EditorView.vue. apply-brand-kit writes through the existing set_edl, and
// EditorView.vue already renders every version's authored_kind; this screen
// only needs to link to /editor/{projectId} afterward.
import { onMounted, ref } from "vue";
import { api, ApiError } from "../api";

interface BrandKit {
  id: string;
  name: string;
  logo_asset_id: string;
  primary_color: string | null;
  secondary_color: string | null;
  font_family: string | null;
  created_by: string;
  updated_at: string;
}
interface Project {
  id: string;
  title: string;
  edl_version: number;
}

const loading = ref(true);
const error = ref<string | null>(null);
const kits = ref<BrandKit[]>([]);
const projects = ref<Project[]>([]);

async function load() {
  loading.value = true;
  error.value = null;
  try {
    const [kitList, projectList] = await Promise.all([api.listBrandKits(), api.listProjects()]);
    kits.value = kitList.brand_kits;
    projects.value = projectList.projects;
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : "could not reach the server";
  } finally {
    loading.value = false;
  }
}
onMounted(load);

// The SPA's /media route renders its refusal as an HTML page, not JSON —
// same reason MediaView.vue parses the DOM rather than expecting a JSON
// body: the storage-ceiling refusal and the missing-declaration refusal both
// need to reach the operator with their real message, not one hardcoded guess.
function parseErrorPage(html: string): string | null {
  try {
    const doc = new DOMParser().parseFromString(html, "text/html");
    const code = doc.querySelector("h1")?.textContent?.trim();
    const message = doc.querySelector(".banner.bad")?.textContent?.trim();
    if (!message) return null;
    return code ? `${code}: ${message}` : message;
  } catch {
    return null;
  }
}

// --- create form -------------------------------------------------------

const name = ref("");
const primaryColor = ref("#4285f4");
const secondaryColor = ref("#f4b400");
const fontFamily = ref("");
const authorship = ref("");
const thirdParty = ref("");
const file = ref<File | null>(null);
const creating = ref(false);
const createError = ref<string | null>(null);

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  file.value = input.files?.[0] ?? null;
}

async function uploadLogo(): Promise<string> {
  const form = new FormData();
  form.append("file", file.value as File);
  form.append("authorship", authorship.value);
  form.append("third_party_material", thirdParty.value);
  const response = await fetch("/media", { method: "POST", body: form, credentials: "same-origin" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(parseErrorPage(text) ?? `logo upload failed (HTTP ${response.status})`);
  }
  const assetId = new URL(response.url).pathname.split("/").filter(Boolean).pop();
  if (!assetId) throw new Error("logo uploaded, but the asset id could not be read from the redirect");
  return assetId;
}

async function createKit() {
  if (!name.value.trim() || !file.value || !authorship.value) return;
  creating.value = true;
  createError.value = null;
  try {
    const logoAssetId = await uploadLogo();
    await api.createBrandKit(
      name.value.trim(),
      logoAssetId,
      primaryColor.value,
      secondaryColor.value,
      fontFamily.value || undefined,
    );
    name.value = "";
    fontFamily.value = "";
    authorship.value = "";
    thirdParty.value = "";
    file.value = null;
    const input = document.querySelector<HTMLInputElement>("#logo-file");
    if (input) input.value = "";
    await load();
  } catch (err) {
    createError.value =
      err instanceof ApiError ? err.message : err instanceof Error ? err.message : "could not create the brand kit";
  } finally {
    creating.value = false;
  }
}

// --- per-kit: rename/recolour, delete, apply ----------------------------
// Logo replacement is NOT exposed inline (a real, disclosed gap, not an
// oversight): update-brand-kit supports a new logo_asset_id, but re-running
// the full declaration-gated upload flow inside an edit row roughly doubles
// this screen's surface for a rare operation. Delete-and-recreate covers it
// today.

const editingId = ref<string | null>(null);
const editName = ref("");
const editPrimary = ref("");
const editSecondary = ref("");
const editFont = ref("");
const savingEdit = ref(false);
const editError = ref<Record<string, string | null>>({});

function startEdit(kit: BrandKit) {
  editingId.value = kit.id;
  editName.value = kit.name;
  editPrimary.value = kit.primary_color ?? "#4285f4";
  editSecondary.value = kit.secondary_color ?? "#f4b400";
  editFont.value = kit.font_family ?? "";
}
function cancelEdit() {
  editingId.value = null;
}
async function saveEdit(kitId: string) {
  if (!editName.value.trim()) return;
  savingEdit.value = true;
  editError.value = { ...editError.value, [kitId]: null };
  try {
    await api.updateBrandKit(kitId, editName.value.trim(), editPrimary.value, editSecondary.value, editFont.value || "");
    editingId.value = null;
    await load();
  } catch (err) {
    editError.value = { ...editError.value, [kitId]: err instanceof ApiError ? err.message : "could not save" };
  } finally {
    savingEdit.value = false;
  }
}

const deletingId = ref<string | null>(null);
async function deleteKit(kit: BrandKit) {
  if (!confirm(`Delete "${kit.name}"? Any project it was already applied to keeps its own EDL version untouched (DR-021) — this only removes the kit itself.`)) {
    return;
  }
  deletingId.value = kit.id;
  try {
    await api.deleteBrandKit(kit.id);
    await load();
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : "could not delete";
  } finally {
    deletingId.value = null;
  }
}

const POSITIONS = ["bottom_right", "bottom_left", "top_right", "top_left", "center"];
const applyProject = ref<Record<string, string>>({});
const applyPosition = ref<Record<string, string>>({});
const applying = ref<Record<string, boolean>>({});
const applyResult = ref<Record<string, { ok: boolean; message: string; projectId?: string } | null>>({});

async function applyKit(kit: BrandKit) {
  const projectId = applyProject.value[kit.id];
  if (!projectId) return;
  applying.value = { ...applying.value, [kit.id]: true };
  applyResult.value = { ...applyResult.value, [kit.id]: null };
  try {
    const result = await api.applyBrandKit(kit.id, projectId, applyPosition.value[kit.id]);
    applyResult.value = {
      ...applyResult.value,
      [kit.id]: { ok: true, message: `Applied — the project is now v${result.edl_version}.`, projectId },
    };
  } catch (err) {
    const message = err instanceof ApiError ? err.message : "could not apply this kit";
    applyResult.value = { ...applyResult.value, [kit.id]: { ok: false, message } };
  } finally {
    applying.value = { ...applying.value, [kit.id]: false };
  }
}
</script>

<template>
  <section class="brandkits">
    <div class="head">
      <div>
        <h1>Brand kits</h1>
        <p class="muted">
          A name, a logo and two colours, applied to a project as a burned-in watermark. Applying a kit writes a
          new EDL version — it never becomes a live input a render depends on, so deleting a kit later never
          touches a render already made from it.
        </p>
      </div>
    </div>

    <form class="create" @submit.prevent="createKit">
      <h2>New brand kit</h2>
      <div class="fields">
        <input v-model="name" type="text" placeholder="Kit name, e.g. 'Main channel'" required />
        <label class="color-field">
          Primary <input v-model="primaryColor" type="color" />
        </label>
        <label class="color-field">
          Secondary <input v-model="secondaryColor" type="color" />
        </label>
        <input v-model="fontFamily" type="text" placeholder="Font family (optional), e.g. 'Inter'" />
      </div>
      <div class="logo-upload">
        <input id="logo-file" type="file" accept="image/*" @change="onFileChange" required />
        <div class="decl">
          <label><input type="radio" value="operator_original" v-model="authorship" required /> My own logo</label>
          <label><input type="radio" value="third_party" v-model="authorship" /> Contains third-party material</label>
          <label><input type="radio" value="unknown" v-model="authorship" /> Unknown</label>
        </div>
        <input
          v-if="authorship === 'third_party'"
          v-model="thirdParty"
          type="text"
          placeholder="What third-party material (one line each, separated by ;)"
        />
      </div>
      <button class="btn primary" type="submit" :disabled="creating || !name.trim() || !file || !authorship">
        {{ creating ? "Creating…" : "Create brand kit" }}
      </button>
      <span v-if="createError" class="banner bad">{{ createError }}</span>
    </form>

    <div v-if="loading" class="state muted">Loading…</div>
    <div v-else-if="error" class="state banner bad">{{ error }}</div>
    <div v-else-if="!kits.length" class="state muted">No brand kits yet. Create one above.</div>
    <div v-else class="scroll">
      <div class="cards">
        <div v-for="kit in kits" :key="kit.id" class="card">
          <template v-if="editingId === kit.id">
            <div class="card-body edit-body">
              <input v-model="editName" type="text" required />
              <div class="fields">
                <label class="color-field">Primary <input v-model="editPrimary" type="color" /></label>
                <label class="color-field">Secondary <input v-model="editSecondary" type="color" /></label>
              </div>
              <input v-model="editFont" type="text" placeholder="Font family" />
              <div class="row-actions">
                <button class="btn primary" type="button" :disabled="savingEdit || !editName.trim()" @click="saveEdit(kit.id)">
                  {{ savingEdit ? "Saving…" : "Save" }}
                </button>
                <button class="btn" type="button" @click="cancelEdit">Cancel</button>
              </div>
              <span v-if="editError[kit.id]" class="banner bad small">{{ editError[kit.id] }}</span>
            </div>
          </template>
          <template v-else>
            <div class="card-head">
              <img class="logo" :src="`/media/${kit.logo_asset_id}/file`" :alt="`${kit.name} logo`" />
              <div class="card-title-wrap">
                <span class="card-title">{{ kit.name }}</span>
                <span class="muted small mono">{{ kit.font_family || "no font set" }}</span>
              </div>
              <div class="swatches">
                <span class="swatch" :style="{ background: kit.primary_color || 'transparent' }" title="Primary" />
                <span class="swatch" :style="{ background: kit.secondary_color || 'transparent' }" title="Secondary" />
              </div>
            </div>
            <div class="card-body">
              <div class="row-actions">
                <button class="btn" type="button" @click="startEdit(kit)">Rename / recolour</button>
                <button class="btn danger" type="button" :disabled="deletingId === kit.id" @click="deleteKit(kit)">
                  {{ deletingId === kit.id ? "Deleting…" : "Delete" }}
                </button>
              </div>

              <div class="apply">
                <h3>Apply to a project</h3>
                <div v-if="!projects.length" class="muted small">No projects yet.</div>
                <div v-else class="apply-row">
                  <select v-model="applyProject[kit.id]">
                    <option value="" disabled selected>Choose a project…</option>
                    <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.title }} (v{{ p.edl_version }})</option>
                  </select>
                  <select v-model="applyPosition[kit.id]">
                    <option v-for="pos in POSITIONS" :key="pos" :value="pos">{{ pos.replaceAll("_", " ") }}</option>
                  </select>
                  <button
                    class="btn primary"
                    type="button"
                    :disabled="applying[kit.id] || !applyProject[kit.id]"
                    @click="applyKit(kit)"
                  >
                    {{ applying[kit.id] ? "Applying…" : "Apply" }}
                  </button>
                </div>
                <p v-if="applyResult[kit.id]" class="apply-result small" :class="{ bad: !applyResult[kit.id]?.ok }">
                  {{ applyResult[kit.id]?.message }}
                  <router-link v-if="applyResult[kit.id]?.ok" :to="`/editor/${applyResult[kit.id]?.projectId}`">
                    Open in editor →
                  </router-link>
                </p>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.brandkits {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 20px 28px 36px;
  overflow-y: auto;
}
.head {
  margin-bottom: 14px;
}
h1 {
  margin: 0;
  font: 600 20px var(--font-ui);
}
p.muted {
  max-width: 68ch;
  color: var(--fg-muted-2);
}
.create {
  background: var(--bg-panel);
  border: 1px solid var(--line-3);
  border-radius: var(--radius-lg);
  padding: 14px 16px;
  margin-bottom: 22px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.create h2 {
  margin: 0;
  font: 600 13px var(--font-ui);
}
.fields {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}
.fields input[type="text"] {
  flex: 1;
  min-width: 200px;
}
.color-field {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--fg-muted-2);
}
.color-field input[type="color"] {
  width: 32px;
  height: 26px;
  padding: 0;
  border: 1px solid var(--line-5);
  border-radius: 5px;
  background: none;
  cursor: pointer;
}
.logo-upload {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.decl {
  display: flex;
  gap: 10px;
  font-size: 12px;
  flex-wrap: wrap;
}
.decl label {
  display: flex;
  align-items: center;
  gap: 4px;
}
input[type="text"],
select {
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
  padding: 0.5rem 0.9rem;
  border-radius: 7px;
  font: 600 12px var(--font-ui);
  background: var(--bg-chip);
  border: 1px solid var(--line-5);
  color: var(--fg-dim);
}
.btn:hover {
  background: var(--bg-card);
}
.btn:focus-visible {
  outline: var(--focus-ring);
  outline-offset: 2px;
}
.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.btn.primary {
  background: var(--green);
  color: var(--green-ink);
  border-color: transparent;
}
.btn.danger {
  color: var(--red-soft, var(--red));
}
.banner {
  border-left: 4px solid var(--amber);
  background: var(--bg-panel);
  padding: 0.6rem 0.85rem;
  border-radius: 0 6px 6px 0;
  font-size: 12.5px;
}
.banner.bad {
  border-left-color: var(--red);
}
.state {
  padding: 30px 0;
}
.scroll {
  flex: 1;
  min-height: 0;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
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
  padding: 12px 14px;
  border-bottom: 1px solid var(--line-3);
  display: flex;
  align-items: center;
  gap: 10px;
}
.logo {
  width: 36px;
  height: 36px;
  object-fit: contain;
  border-radius: 6px;
  background: var(--bg-field);
  flex: none;
}
.card-title-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.card-title {
  font: 600 13px var(--font-ui);
}
.swatches {
  display: flex;
  gap: 4px;
  flex: none;
}
.swatch {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 1px solid var(--line-5);
}
.card-body {
  padding: 12px 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.edit-body input[type="text"] {
  width: 100%;
  box-sizing: border-box;
}
.row-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.apply h3 {
  margin: 0 0 6px;
  font: 600 10.5px var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--fg-muted-3);
}
.apply-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.apply-row select {
  flex: 1;
  min-width: 120px;
}
.apply-result {
  margin: 8px 0 0;
  line-height: 1.4;
}
.apply-result.bad {
  color: var(--red-soft, var(--red));
}
.small {
  font-size: 11px;
}
</style>
