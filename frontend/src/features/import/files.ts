// Сбор файлов из перетаскивания (включая вложенные папки) и выбора файлов/папки.

export interface PickedFile {
  file: File;
  path: string; // относительный путь: папка/имя — из него сервис понимает группы «одна папка = один товар»
}

function readEntry(entry: FileSystemEntry, prefix: string): Promise<PickedFile[]> {
  return new Promise((resolve) => {
    if (entry.isFile) {
      (entry as FileSystemFileEntry).file((f) => resolve([{ file: f, path: prefix + f.name }]), () => resolve([]));
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      const all: FileSystemEntry[] = [];
      const next = () =>
        reader.readEntries(async (es) => {
          if (!es.length) {
            const sub = await Promise.all(all.map((e) => readEntry(e, prefix + entry.name + "/")));
            resolve(sub.flat());
          } else {
            all.push(...es);
            next();
          }
        }, () => resolve([]));
      next();
    } else {
      resolve([]);
    }
  });
}

export async function filesFromDrop(dt: DataTransfer): Promise<PickedFile[]> {
  const entries = [...dt.items].map((i) => i.webkitGetAsEntry()).filter((e): e is FileSystemEntry => !!e);
  if (entries.length) return (await Promise.all(entries.map((e) => readEntry(e, "")))).flat();
  return [...dt.files].map((f) => ({ file: f, path: f.name }));
}

export function filesFromInput(list: FileList | null): PickedFile[] {
  return [...(list || [])].map((f) => ({ file: f, path: f.webkitRelativePath || f.name }));
}
