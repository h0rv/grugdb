// The browser stores edits, not copies of the supplied files or a second engine.
export function validPath(path) {
  return typeof path === "string" && /^(?:src\/grugdb|tests)\/(?:[A-Za-z_]\w*\/)*[A-Za-z_]\w*\.py$/.test(path);
}

export function readBackup(value, manifest) {
  if (!value || value.version !== 1 || typeof value.revision !== "string" ||
      !value.files || typeof value.files !== "object" || Array.isArray(value.files)) {
    throw new Error("Choose a grugdb workspace JSON backup.");
  }
  const entries = Object.entries(value.files);
  for (const [path, text] of entries) {
    if (!validPath(path) || typeof text !== "string" ||
        (Object.hasOwn(manifest.files, path) && !manifest.editable.includes(path))) {
      throw new Error(`Cannot import ${path}. Supplied tests cannot be replaced.`);
    }
  }
  return Object.fromEntries(entries);
}

export function projectFiles(manifest, edits) {
  return {...manifest.files, ...edits};
}

export function saveEdit(edits, manifest, path, text) {
  if (text === manifest.files[path]) delete edits[path];
  else edits[path] = text;
}

function sourceKey(record, revision) {
  const files = Object.entries(record?.files ?? {}).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
  return JSON.stringify([record?.revision ?? revision, files]);
}

export async function openStorage() {
  const db = await new Promise((resolve, reject) => {
    const request = indexedDB.open("grugdb-workspace-v1", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("workspace");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Close other course tabs to enable autosave."));
  });
  const record = await new Promise((resolve, reject) => {
    const tx = db.transaction("workspace", "readonly");
    const request = tx.objectStore("workspace").get("work");
    request.onsuccess = () => resolve(request.result ?? null);
    request.onerror = () => reject(request.error);
  });
  let baselineSource = record ? sourceKey(record) : null;
  db.onversionchange = () => db.close();
  return {
    record,
    write(value) {
      const nextSource = sourceKey(value);
      return new Promise((resolve, reject) => {
        const tx = db.transaction("workspace", "readwrite");
        const store = tx.objectStore("workspace");
        const request = store.get("work");
        let conflict = false;
        let nextSequence;
        request.onsuccess = () => {
          const current = request.result;
          const currentSource = sourceKey(current, value.revision);
          const expectedSource = baselineSource ?? sourceKey(null, value.revision);
          // Result-only saves do not invalidate the source this tab read.
          // A changed source must still conflict unless the new source agrees.
          if (currentSource !== expectedSource && currentSource !== nextSource) {
            conflict = true;
            tx.abort();
          } else {
            nextSequence = (current?.sequence ?? 0) + 1;
            store.put({...value, sequence: nextSequence}, "work");
          }
        };
        tx.oncomplete = () => { baselineSource = nextSource; resolve(); };
        tx.onabort = () => reject(conflict
          ? new Error("Another tab saved changes. Export your work before reloading this tab.")
          : tx.error ?? new Error("Autosave failed. Export a backup of your work."));
        tx.onerror = () => {};
      });
    },
  };
}
