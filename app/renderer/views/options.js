// Options: settings of the app itself - the style (1984 / classic), the Overseer's eye, the user's own background
// images (JPG / PNG, kept by the backend in <data dir>/backgrounds) with their transparency, the window and the tabs.
import { h, card, notice, toast, viewHeader } from '../lib/dom.js';
import { FITS, THEMES, applyOptions, backgroundUri, loadOptions, saveOptions } from '../lib/options.js';

const MAX_MB = 12;

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error ?? new Error('The file could not be read'));
    reader.readAsDataURL(file);
  });
}

function slider(value, min, max, onInput, unit = '%') {
  const out = h('output', { class: 'opt-value' }, `${value}${unit}`);
  const input = h('input', { type: 'range', min, max, step: 1, value, class: 'opt-range',
    oninput: (e) => { out.textContent = `${e.target.value}${unit}`; onInput(+e.target.value); } });
  return h('span', { class: 'opt-slider' }, input, out);
}

function row(label, hint, ...control) {
  return h('div', { class: 'opt-row' }, h('div', { class: 'opt-label' }, h('strong', null, label), hint ? h('span', { class: 'muted' }, hint) : null),
    h('div', { class: 'opt-control' }, ...control));
}

function check(checked, onChange, label) {
  return h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: checked || null, onchange: (e) => onChange(e.target.checked) }),
    h('span', null, label));
}

export default {
  id: 'options',
  title: 'Options',
  short: 'OP',
  async render(root, ctx) {
    let o = loadOptions();
    let images = [];
    let busy = false;
    const set = (patch, rerender = false) => {
      o = { ...o, ...patch };
      saveOptions(o);
      applyOptions(o, ctx.api);
      if (rerender) draw();
    };
    const appearance = h('div');
    const gallery = h('div', { class: 'opt-gallery' });
    const layout = h('div');

    async function loadImages() {
      try {
        images = (await ctx.api.get('/api/backgrounds')).data;
      } catch (err) {
        images = [];
        gallery.replaceChildren(notice('warn', `Background images unavailable: ${err.message}`));
        return;
      }
      if (o.image && !images.some((b) => b.id === o.image)) set({ image: null });
      drawGallery();
    }

    async function addImages(files) {
      busy = true;
      drawGallery();
      for (const file of files) {
        if (!/\.(jpe?g|png)$/i.test(file.name) || !/^image\/(jpeg|png)$/.test(file.type)) {
          toast(`${file.name}: only JPG and PNG images`, 'error');
          continue;
        }
        if (file.size > MAX_MB * 1024 * 1024) {
          toast(`${file.name}: larger than ${MAX_MB} MB`, 'error');
          continue;
        }
        try {
          const item = (await ctx.api.post('/api/backgrounds', { name: file.name, data: await readFile(file) })).data;
          images.push(item);
          set({ image: item.id });
          toast(`Background ${file.name} added`, 'ok');
        } catch (err) {
          toast(`${file.name}: ${err.message}`, 'error');
        }
      }
      busy = false;
      drawGallery();
    }

    async function remove(b) {
      if (!window.confirm(`Delete the background ${b.name}?`)) return;
      try {
        images = (await ctx.api.post(`/api/backgrounds/${b.id}/delete`, {})).data;
        if (o.image === b.id) set({ image: null });
        drawGallery();
      } catch (err) {
        toast(`Not deleted: ${err.message}`, 'error');
      }
    }

    function thumb(b) {
      const box = h('button', { class: `opt-thumb ${o.image === b.id ? 'opt-thumb-on' : ''}`, title: b.name,
        'aria-pressed': String(o.image === b.id), onclick: () => { set({ image: b.id }); drawGallery(); } },
      h('span', { class: 'opt-thumb-name' }, b.name));
      backgroundUri(ctx.api, b.id).then((uri) => { box.style.backgroundImage = `url("${uri}")`; }, () => box.classList.add('opt-thumb-bad'));
      return h('div', { class: 'opt-thumb-wrap' }, box,
        h('button', { class: 'opt-thumb-del', title: `Delete ${b.name}`, onclick: () => remove(b) }, '×'));
    }

    function drawGallery() {
      const input = h('input', { type: 'file', accept: '.jpg,.jpeg,.png,image/jpeg,image/png', multiple: true, hidden: true,
        onchange: (e) => { addImages([...e.target.files]); e.target.value = ''; } });
      gallery.replaceChildren(
        h('div', { class: 'opt-thumb-wrap' }, h('button', { class: `opt-thumb opt-thumb-none ${o.image ? '' : 'opt-thumb-on'}`,
          'aria-pressed': String(!o.image), onclick: () => { set({ image: null }); drawGallery(); } }, 'No image')),
        ...images.map(thumb),
        h('div', { class: 'opt-thumb-wrap' }, h('button', { class: 'opt-thumb opt-thumb-add', disabled: busy || null,
          onclick: () => input.click() }, busy ? 'Adding…' : '+ Add image'), input));
    }

    function draw() {
      appearance.replaceChildren(...[
        row('Style', 'Colours, fonts and the look of the panels.',
          h('div', { class: 'gs-seg' }, Object.entries(THEMES).map(([k, label]) => h('button', {
            class: `gs-seg-btn ${o.theme === k ? 'gs-seg-on' : ''}`, 'aria-pressed': String(o.theme === k),
            onclick: () => set(k === 'classic' ? { theme: k, eye: false } : { theme: k, eye: true }, true) }, label)))),
        row('The Overseer\'s eye', 'The large eye behind the views.',
          check(o.eye, (v) => set({ eye: v }, true), 'Show'),
          o.eye ? slider(o.eyeOpacity, 0, 100, (v) => set({ eyeOpacity: v })) : null),
        o.eye ? row('Eye behaviour', null, check(o.eyeTrack, (v) => set({ eyeTrack: v }), 'Follows the cursor'),
          check(o.eyeBlink, (v) => set({ eyeBlink: v }), 'Blinks')) : null,
        row('Background image', `Your own JPG or PNG images (up to ${MAX_MB} MB each), kept in the app's data folder.`, gallery),
        o.image ? row('Image transparency', '0% = invisible, 100% = full image.',
          slider(o.imageOpacity, 0, 100, (v) => set({ imageOpacity: v }))) : null,
        o.image ? row('Image placement', null,
          h('select', { class: 'input', onchange: (e) => set({ imageFit: e.target.value }) },
            Object.entries(FITS).map(([k, label]) => h('option', { value: k, selected: o.imageFit === k || null }, label))),
          h('span', { class: 'muted' }, 'Blur'), slider(o.imageBlur, 0, 20, (v) => set({ imageBlur: v }), ' px')) : null,
        row('', null, h('button', { class: 'btn btn-small btn-ghost', onclick: () => {
          set({ theme: '1984', eye: true, eyeOpacity: 22, eyeTrack: true, eyeBlink: true, image: null, imageOpacity: 35,
            imageFit: 'cover', imageBlur: 0 }, true);
          drawGallery();
        } }, 'Restore the default look'))].filter(Boolean));   // replaceChildren would print a null
      layout.replaceChildren(
        row('Start tab', 'The tab the app opens with.',
          h('select', { class: 'input', onchange: (e) => set({ startTab: e.target.value }) },
            h('option', { value: '' }, 'Dashboard'),
            ctx.views.filter((v) => v.id !== 'dashboard').map((v) => h('option', { value: v.id, selected: o.startTab === v.id || null }, v.title)))),
        row('Compact mode', 'Denser layout for a small window next to the game.',
          check(ctx.state.compact, (v) => ctx.setState({ compact: v }), 'Enabled')),
        row('Always on top', 'Keeps this window above the game window.',
          check(ctx.state.alwaysOnTop, (v) => ctx.setAlwaysOnTop(v), 'Enabled')),
        row('Tab order', 'Drag the tabs in the sidebar (or Alt+Up / Alt+Down) to change it.',
          h('button', { class: 'btn btn-small', onclick: () => { ctx.resetNavOrder(); toast('Default tab order', 'ok'); } }, 'Reset tab order')));
    }

    draw();
    drawGallery();
    root.append(
      viewHeader('Options', 'Settings of this app - nothing here changes the game.'),
      card('Appearance', appearance),
      card('Window and tabs', layout),
      card('More options later', h('ul', { class: 'opt-ideas' },
        h('li', null, 'Notifications: which alerts (national focus, construction, recording) show as Windows notifications.'),
        h('li', null, 'Refresh rates of live game memory reading (faster or lighter on the CPU).'),
        h('li', null, 'Language of the app (Polish / English) and number format.'),
        h('li', null, 'Data: open the data folder, size of the recorded campaigns, delete old recordings, export / import these settings.'),
        h('li', null, 'Text size and keyboard shortcuts.')), { cls: 'opt-later' }),
    );
    await loadImages();
  },
};
