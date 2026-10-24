<script setup lang="ts">
// Документы операции: чек (один) и сопутствующие файлы. Просмотр PDF и картинок прямо в приложении,
// остальное скачивается. Если сервер ещё без поддержки вложений, честно говорим об этом.
import { Download, Eye, FileText, Image, Paperclip, Plus, Receipt, Trash2, X } from 'lucide-vue-next'
import { computed, defineAsyncComponent, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, ApiError, downloadAttachment, previewUrl, type Attachment } from '../api'
import { fileSize, humanDate } from '../format'
import AttachmentUploadDialog from './AttachmentUploadDialog.vue'
const PdfPreview = defineAsyncComponent(() => import('./PdfPreview.vue'))

const props = defineProps<{ operationId: string }>()
const toast = inject<(t: string) => void>('toast', () => {})
const items = ref<Attachment[]>([])
const state = ref<'loading' | 'ready' | 'unsupported' | 'error'>('loading')
const errorText = ref('')
const upload = ref<'receipt' | 'related' | null>(null)
const preview = ref<{ att: Attachment; url: string } | null>(null)
const previewDialog = ref<HTMLDialogElement | null>(null)
const confirmDelete = ref<string | null>(null)

const receipt = computed(() => items.value.find((a) => a.kind === 'receipt') ?? null)
const related = computed(() => items.value.filter((a) => a.kind === 'related'))

async function load() {
  state.value = 'loading'
  try { items.value = await api.attachments(props.operationId); state.value = 'ready' }
  catch (e) {
    // У FastAPI неизвестный маршрут отвечает 404 «Not Found»; у нас «Операция не найдена» — это другое.
    if (e instanceof ApiError && e.status === 404 && !e.message.includes('Операция')) state.value = 'unsupported'
    else { state.value = 'error'; errorText.value = e instanceof ApiError ? e.message : 'Не удалось загрузить список файлов' }
  }
}
onMounted(load)

async function open(att: Attachment) {
  try {
    if (!att.previewable) { await downloadAttachment(att); return }
    preview.value = { att, url: await previewUrl(att) }
    requestAnimationFrame(() => previewDialog.value?.showModal())
  } catch (e) { toast(e instanceof ApiError ? e.message : 'Не удалось открыть файл') }
}
function closePreview() {
  previewDialog.value?.close()
  if (preview.value) URL.revokeObjectURL(preview.value.url)
  preview.value = null
}
onBeforeUnmount(() => { if (preview.value) URL.revokeObjectURL(preview.value.url) })

async function download(att: Attachment) {
  try { await downloadAttachment(att) } catch (e) { toast(e instanceof ApiError ? e.message : 'Не удалось скачать файл') }
}
async function remove(att: Attachment) {
  try {
    await api.deleteAttachment(att.id)
    items.value = items.value.filter((a) => a.id !== att.id)
    confirmDelete.value = null
    toast('Файл удалён')
  } catch (e) { toast(e instanceof ApiError ? e.message : 'Не удалось удалить файл') }
}
function onSaved(next: Attachment[]) {
  if (next.length) items.value = next
  upload.value = null
  toast('Файлы загружены')
}
const iconFor = (a: Attachment) => (a.content_type.startsWith('image/') ? Image : FileText)
</script>

<template>
  <div class="docs">
    <p v-if="state === 'loading'" class="tiny">Загружаем список файлов…</p>
    <p v-else-if="state === 'unsupported'" class="small muted">Вложения заработают после обновления сервера.</p>
    <p v-else-if="state === 'error'" class="error">{{ errorText }} <button class="btn btn-ghost btn-sm" @click="load">Повторить</button></p>
    <template v-else>
      <div class="slot">
        <p class="slot-label"><Receipt aria-hidden="true" />Чек</p>
        <div v-if="receipt" class="file">
          <component :is="iconFor(receipt)" class="f-ico" aria-hidden="true" />
          <button class="f-name" :title="receipt.filename" @click="open(receipt)">{{ receipt.filename }}</button>
          <span class="tiny">{{ fileSize(receipt.size_bytes) }}</span>
          <div class="f-act">
            <template v-if="confirmDelete === receipt.id">
              <button class="btn btn-danger btn-sm" @click="remove(receipt)">Удалить</button>
              <button class="btn btn-ghost btn-sm" @click="confirmDelete = null">Нет</button>
            </template>
            <template v-else>
              <button v-if="receipt.previewable" class="btn btn-ghost btn-icon" :aria-label="`Открыть ${receipt.filename}`" @click="open(receipt)"><Eye /></button>
              <button class="btn btn-ghost btn-icon" :aria-label="`Скачать ${receipt.filename}`" @click="download(receipt)"><Download /></button>
              <button class="btn btn-ghost btn-icon" :aria-label="`Удалить ${receipt.filename}`" @click="confirmDelete = receipt.id"><Trash2 /></button>
            </template>
          </div>
        </div>
        <p v-else class="small muted">Чек не прикреплён.</p>
        <button class="btn btn-sm" @click="upload = 'receipt'"><Paperclip />{{ receipt ? 'Заменить чек' : 'Прикрепить чек' }}</button>
      </div>

      <div class="slot">
        <p class="slot-label"><FileText aria-hidden="true" />Сопутствующие файлы <span class="tiny">{{ related.length || '' }}</span></p>
        <ul v-if="related.length" class="list">
          <li v-for="a in related" :key="a.id" class="file">
            <component :is="iconFor(a)" class="f-ico" aria-hidden="true" />
            <button class="f-name" :title="a.filename" @click="open(a)">{{ a.filename }}</button>
            <span class="tiny">{{ fileSize(a.size_bytes) }} · {{ humanDate(a.created_at) }}</span>
            <div class="f-act">
              <template v-if="confirmDelete === a.id">
                <button class="btn btn-danger btn-sm" @click="remove(a)">Удалить</button>
                <button class="btn btn-ghost btn-sm" @click="confirmDelete = null">Нет</button>
              </template>
              <template v-else>
                <button v-if="a.previewable" class="btn btn-ghost btn-icon" :aria-label="`Открыть ${a.filename}`" @click="open(a)"><Eye /></button>
                <button class="btn btn-ghost btn-icon" :aria-label="`Скачать ${a.filename}`" @click="download(a)"><Download /></button>
                <button class="btn btn-ghost btn-icon" :aria-label="`Удалить ${a.filename}`" @click="confirmDelete = a.id"><Trash2 /></button>
              </template>
            </div>
          </li>
        </ul>
        <p v-else class="small muted">Акт, договор или накладная к этому платежу.</p>
        <button class="btn btn-sm" @click="upload = 'related'"><Plus />Добавить файлы</button>
      </div>
      <p class="tiny">Файлы видите только вы. Ассистент и модель прогноза их не читают.</p>
    </template>

    <AttachmentUploadDialog v-if="upload" :operation-id="operationId" :has-receipt="!!receipt" :mode="upload"
                            @close="upload = null" @saved="onSaved" @updated="items = $event" />

    <dialog v-if="preview" ref="previewDialog" class="modal preview" aria-label="Просмотр файла" @cancel.prevent="closePreview">
      <div class="p-head">
        <p class="p-name">{{ preview.att.filename }}</p>
        <button class="btn btn-sm" @click="download(preview.att)"><Download />Скачать</button>
        <button class="btn btn-ghost btn-icon" aria-label="Закрыть" @click="closePreview"><X /></button>
      </div>
      <img v-if="preview.att.content_type.startsWith('image/')" :src="preview.url" :alt="preview.att.filename" class="p-img" />
      <PdfPreview v-else :key="preview.url" :url="preview.url" :filename="preview.att.filename" />
    </dialog>
  </div>
</template>

<style scoped>
.docs { display: grid; gap: 16px; }
.slot { display: grid; gap: 8px; justify-items: start; }
.slot-label { display: flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600; }
.slot-label svg { width: 16px; height: 16px; color: var(--ink-3); }
.list { list-style: none; padding: 0; margin: 0; display: grid; gap: 4px; width: 100%; }
.file { display: flex; align-items: center; gap: 10px; width: 100%; padding: 6px 6px 6px 10px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-s); }
.f-ico { width: 18px; height: 18px; color: var(--ink-3); flex: none; }
.f-name { flex: 1; min-width: 0; text-align: left; background: none; border: 0; padding: 0; cursor: pointer; font-weight: 550; font-size: 14px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink); }
.f-name:hover { color: var(--brand); text-decoration: underline; }
.f-act { display: flex; gap: 2px; flex: none; }
.preview { width: min(960px, calc(100% - 32px)); height: calc(100dvh - 64px); display: flex; flex-direction: column; }
.preview[open] { display: flex; }
.p-head { display: flex; align-items: center; gap: 8px; padding: 12px 12px 12px 20px; border-bottom: 1px solid var(--line); }
.p-name { flex: 1; min-width: 0; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.p-img { flex: 1; min-height: 0; object-fit: contain; background: var(--bg); width: 100%; }
.p-frame { flex: 1; border: 0; width: 100%; }
@media (max-width: 560px) { .file .tiny { display: none; } }
</style>
