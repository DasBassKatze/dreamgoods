const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const web = path.join(__dirname, "../dreamgoods/web");
const base = "http://dreamgoods.test";
const project = { id: 1, name: "Перенос ткани", client: "Тест" };
const state = {
  admin: false, account: { balance: 200, billing: true }, project, presets: [], products: [],
  settings: { plan: {}, model: "test" }, warnings: [], runner: { busy: false, queued: 0, running: 0 },
  log: [], totals: { done: 0, total: 0, review: 0 }, balance: null,
};

async function png(page, width, height, color) {
  const encoded = await page.evaluate(({ width, height, color }) => {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, width, height);
    return canvas.toDataURL().split(",")[1];
  }, { width, height, color });
  return Buffer.from(encoded, "base64");
}

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN || undefined,
    headless: true, args: ["--no-sandbox"] });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    let job = null, resultId = null, upload, output, submitCount = 0;
    await page.route(`${base}/**`, async route => {
      const { pathname, searchParams } = new URL(route.request().url());
      if (pathname === "/studio" || pathname.startsWith("/assets/")) {
        return route.fulfill({ path: path.join(web, pathname === "/studio" ? "index.html" : pathname) });
      }
      let json = {};
      if (pathname === "/api/auth/me") {
        json = { id: 1, org_id: 1, email: "test", name: "Тест", role: "user",
          client: { id: 1, balance: 200, billing: true }, consents_required: [] };
      } else if (pathname === "/api/projects") {
        json = { projects: [project] };
      } else if (pathname.endsWith("/state")) {
        json = state;
      } else if (pathname.endsWith("/textile")) {
        if (route.request().method() === "POST") {
          upload = route.request().postDataBuffer();
          job = { id: ++submitCount, status: "queued", error: "", has_image: false };
          json = job;
        } else {
          if (job?.id === 1) {
            job = { ...job, status: "done", has_image: true };
            resultId = job.id;
          }
          json = { job, result_id: resultId };
        }
      } else if (pathname.endsWith("/textile/2/cancel")) {
        job = { ...job, status: "cancelled" };
        json = job;
      } else if (pathname.endsWith("/textile/1/image")) {
        const headers = searchParams.has("download") ?
          { "Content-Disposition": 'attachment; filename="textile-transfer-1.png"' } : {};
        return route.fulfill({ body: output, contentType: "image/png", headers });
      }
      return route.fulfill({ json });
    });
    await page.goto(`${base}/studio#/creative`);
    await page.getByRole("button", { name: "Перенос ткани", exact: true }).click();
    assert.equal(await page.evaluate(() => typeof window.dgDesktop), "undefined");
    const garment = await png(page, 120, 160, "#cccccc");
    const fabric = await png(page, 200, 200, "#144d2f");
    output = await png(page, 120, 160, "#144d2f");
    const loadInputs = async () => {
      await page.getByLabel("Фото одежды", { exact: true }).setInputFiles({
        name: "photo.png", mimeType: "image/png", buffer: garment,
      });
      await page.getByLabel("Образец ткани", { exact: true }).setInputFiles({
        name: "tile.png", mimeType: "image/png", buffer: fabric,
      });
      const sample = page.getByRole("img", { name: "Образец ткани для выделения" });
      await sample.waitFor();
      await page.waitForFunction(() => document.querySelector(".fabric-selection img")?.naturalWidth === 200);
      return sample;
    };
    const sample = await loadInputs();
    const { x, y, width, height } = await sample.boundingBox();
    await page.mouse.move(x + width / 4, y + height / 4);
    await page.mouse.down();
    await page.mouse.move(x + 3 * width / 4, y + 3 * height / 4);
    await page.mouse.up();
    await page.getByText("Будет использован выделенный фрагмент").waitFor();
    await page.getByLabel("Дополнительные указания (необязательно)").fill("Оставь рукава без изменений");
    const launch = page.getByRole("button", { name: "Перенести ткань", exact: true });
    await launch.click();
    const preview = page.getByRole("img", { name: "Результат переноса ткани" });
    await preview.waitFor();
    await page.waitForFunction(() => document.querySelector(".creative-result")?.naturalWidth === 120);
    assert(upload.includes(garment), "Original garment photo must remain unchanged");
    assert(upload.includes(Buffer.from("Оставь рукава без изменений")));
    const marker = upload.indexOf('name="fabric"; filename="fabric-fragment.png"');
    assert(marker >= 0);
    const data = upload.indexOf("\r\n\r\n", marker) + 4;
    assert.equal(upload.readUInt32BE(data + 16), 100);
    assert.equal(upload.readUInt32BE(data + 20), 100);
    const [download] = await Promise.all([
      page.waitForEvent("download"), page.getByRole("link", { name: "Скачать результат" }).click(),
    ]);
    assert.equal(download.suggestedFilename(), "textile-transfer-1.png");
    assert.deepEqual(fs.readFileSync(await download.path()), output);

    await page.reload();
    await page.getByRole("button", { name: "Перенос ткани", exact: true }).click();
    await preview.waitFor();
    await loadInputs();
    await launch.click();
    await page.getByRole("button", { name: "Отменить перенос" }).click();
    await page.getByText("Задание остановлено").waitFor();
    await page.getByText("Последний готовый перенос").waitFor();
    assert(await preview.isVisible());
    assert(upload.includes(fabric), "Use the entire fabric photo when there is no selection");
    assert.equal(submitCount, 2);
    assert.deepEqual(errors, []);
    console.log("PASS: web textile crop, optional prompt, image download, reload and cancellation");
  } finally {
    await browser.close();
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
